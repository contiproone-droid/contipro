from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField, EncryptedTextField


def fase_inicial_default():
    stage = PipelineStage.objects.order_by('ordem').first()
    return stage.pk if stage else None


class PipelineStage(models.Model):
    """Uma fase do pipeline, editável via UI (tela 'Configurar pipeline')."""

    nome = models.CharField('Nome da fase', max_length=150)
    ordem = models.PositiveIntegerField('Ordem', unique=True)

    class Meta:
        ordering = ['ordem']
        verbose_name = 'Fase do pipeline'
        verbose_name_plural = 'Fases do pipeline'

    def __str__(self):
        return self.nome

    def excluir_e_realocar(self, usuario=None):
        """Apaga a fase, movendo perfis afetados para a fase vizinha e registrando
        auditoria. Levanta ValueError se for a última fase restante do pipeline."""
        todas = list(PipelineStage.objects.order_by('ordem'))
        if len(todas) <= 1:
            raise ValueError('Não é possível apagar a última fase restante do pipeline.')

        idx = todas.index(self)
        destino = todas[1] if idx == 0 else todas[idx - 1]

        with transaction.atomic():
            for perfil in Profile.objects.filter(fase_atual=self):
                perfil.fase_atual = destino
                perfil.save(update_fields=['fase_atual', 'atualizado_em'])
                PhaseHistory.objects.create(
                    perfil=perfil,
                    fase_nome=destino.nome,
                    usuario=usuario,
                    observacao='Movido automaticamente: a fase anterior foi removida do pipeline.',
                )
            self.delete()

    @staticmethod
    def reordenar(pks_em_ordem):
        """Recebe uma lista de PKs de PipelineStage na nova ordem desejada e persiste.
        Usa um deslocamento temporário para não violar a constraint unique de 'ordem'."""
        with transaction.atomic():
            for indice, pk in enumerate(pks_em_ordem):
                PipelineStage.objects.filter(pk=pk).update(ordem=10_000 + indice)
            for indice, pk in enumerate(pks_em_ordem):
                PipelineStage.objects.filter(pk=pk).update(ordem=indice + 1)


class AuthType(models.TextChoices):
    NENHUMA = 'nenhuma', 'Nenhuma'
    SMS = 'sms', '2FA via SMS'
    APP_AUTENTICADOR = 'app_autenticador', '2FA via app autenticador'
    EMAIL_RECUPERACAO = 'email_recuperacao', 'E-mail de recuperação'


class ProfileStatus(models.TextChoices):
    ATIVO = 'ativo', 'Ativo'
    BANIDO = 'banido', 'Banido'
    SUSPENSO = 'suspenso', 'Suspenso'
    PAUSADO = 'pausado', 'Pausado'


class PageStatus(models.TextChoices):
    CRIADA = 'criada', 'Criada'
    PENDENTE = 'pendente', 'Pendente'
    FALHOU = 'falhou', 'Falhou'


class WhatsAppStatus(models.TextChoices):
    PENDENTE = 'pendente', 'Pendente'
    VINCULADO = 'vinculado', 'Vinculado'
    FALHOU = 'falhou', 'Falhou'


class BusinessManagerStatus(models.TextChoices):
    ATIVO = 'ativo', 'Ativo'
    RESTRITO = 'restrito', 'Restrito'
    BANIDO = 'banido', 'Banido'


class Profile(models.Model):
    """Um perfil (navegador AdsPower) usado para criar/gerir uma conta Facebook Business."""

    nome = models.CharField('Nome/Identificador do perfil', max_length=150)
    email = models.EmailField('E-mail (conta Facebook)')
    senha = EncryptedCharField(
        'Senha',
        max_length=255,
        help_text='Armazenada criptografada (FIELD_ENCRYPTION_KEY). Nunca exibida em texto puro.',
    )
    tipo_autenticacao = models.CharField(
        'Tipo de autenticação',
        max_length=20,
        choices=AuthType.choices,
        default=AuthType.NENHUMA,
    )
    dados_autenticacao = EncryptedTextField(
        'Dados de autenticação adicionais',
        blank=True,
        default='',
        help_text='Códigos de backup/recuperação, segredo do app autenticador etc. Criptografado.',
    )
    adspower_id = models.CharField(
        'Perfil/Proxy no AdsPower',
        max_length=150,
        blank=True,
        help_text='ID do perfil no AdsPower (ex: kp0a1b2c3d4).',
    )
    fase_atual = models.ForeignKey(
        'PipelineStage',
        verbose_name='Fase atual',
        on_delete=models.PROTECT,
        default=fase_inicial_default,
        related_name='perfis',
    )
    status = models.CharField(
        'Status',
        max_length=20,
        choices=ProfileStatus.choices,
        default=ProfileStatus.ATIVO,
    )
    criado_em = models.DateTimeField('Data de criação', auto_now_add=True)
    atualizado_em = models.DateTimeField('Última atualização', auto_now=True)
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='Responsável',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='perfis_responsavel',
    )
    observacoes = models.TextField('Observações/Notas', blank=True)

    class Meta:
        ordering = ['-atualizado_em']
        verbose_name = 'Perfil'
        verbose_name_plural = 'Perfis'

    def __str__(self):
        return self.nome

    def get_absolute_url(self):
        return reverse('profiles:profile_detail', args=[self.pk])

    @property
    def fase_index(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        try:
            return ordem.index(self.fase_atual)
        except ValueError:
            return 0

    @property
    def fases_concluidas(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        return ordem[:self.fase_index]

    @property
    def fase_progress_percent(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        total = len(ordem) - 1
        if total <= 0:
            return 100
        return round(self.fase_index / total * 100)

    @property
    def proxima_fase(self):
        ordem = list(PipelineStage.objects.order_by('ordem'))
        try:
            idx = ordem.index(self.fase_atual)
        except ValueError:
            return None
        if idx >= len(ordem) - 1:
            return None
        return ordem[idx + 1]

    @property
    def is_concluido(self):
        return self.proxima_fase is None

    def avancar_fase(self, usuario=None, observacao=''):
        """Avança o perfil para a próxima fase e registra no histórico. Retorna True se avançou."""
        proxima = self.proxima_fase
        if proxima is None:
            return False
        self.fase_atual = proxima
        self.save(update_fields=['fase_atual', 'atualizado_em'])
        PhaseHistory.objects.create(
            perfil=self,
            fase_nome=proxima.nome,
            usuario=usuario,
            observacao=observacao,
        )
        return True


class PhaseHistory(models.Model):
    """Auditoria: cada mudança de fase de um Profile."""

    perfil = models.ForeignKey(
        Profile,
        verbose_name='Perfil',
        on_delete=models.CASCADE,
        related_name='historico_fases',
    )
    fase_nome = models.CharField('Fase', max_length=150)
    data_hora = models.DateTimeField('Data/hora da mudança', default=timezone.now)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='Usuário',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    observacao = models.TextField('Observação', blank=True)

    class Meta:
        ordering = ['-data_hora']
        verbose_name = 'Histórico de fase'
        verbose_name_plural = 'Histórico de fases'

    def __str__(self):
        return f'{self.perfil.nome} → {self.fase_nome}'


class PageInfo(models.Model):
    """Informações da página do Facebook associada a um perfil."""

    perfil = models.ForeignKey(
        Profile,
        verbose_name='Perfil',
        on_delete=models.CASCADE,
        related_name='paginas',
    )
    nome_pagina = models.CharField('Nome da página', max_length=200)
    link_pagina = models.URLField('Link da página', blank=True)
    data_criacao = models.DateField('Data de criação da página', null=True, blank=True)
    status = models.CharField(
        'Status',
        max_length=20,
        choices=PageStatus.choices,
        default=PageStatus.PENDENTE,
    )

    class Meta:
        ordering = ['-id']
        verbose_name = 'Página do Facebook'
        verbose_name_plural = 'Páginas do Facebook'

    def __str__(self):
        return self.nome_pagina


class WhatsAppLink(models.Model):
    """Vínculo de um número de WhatsApp a um perfil."""

    perfil = models.ForeignKey(
        Profile,
        verbose_name='Perfil',
        on_delete=models.CASCADE,
        related_name='whatsapp_links',
    )
    numero_telefone = models.CharField('Número de telefone vinculado', max_length=30)
    status = models.CharField(
        'Status do vínculo',
        max_length=20,
        choices=WhatsAppStatus.choices,
        default=WhatsAppStatus.PENDENTE,
    )
    data_vinculo = models.DateField('Data do vínculo', null=True, blank=True)

    class Meta:
        ordering = ['-id']
        verbose_name = 'Vínculo do WhatsApp'
        verbose_name_plural = 'Vínculos do WhatsApp'

    def __str__(self):
        return f'{self.numero_telefone} ({self.perfil.nome})'


class BusinessManager(models.Model):
    """Business Manager gerado para o perfil (relação 1-para-1)."""

    perfil = models.OneToOneField(
        Profile,
        verbose_name='Perfil',
        on_delete=models.CASCADE,
        related_name='business_manager',
    )
    bm_id = models.CharField('ID do Business Manager', max_length=100)
    nome_bm = models.CharField('Nome do Business Manager', max_length=200)
    data_geracao = models.DateField('Data de geração', null=True, blank=True)
    status = models.CharField(
        'Status',
        max_length=20,
        choices=BusinessManagerStatus.choices,
        default=BusinessManagerStatus.ATIVO,
    )

    class Meta:
        verbose_name = 'Business Manager'
        verbose_name_plural = 'Business Managers'

    def __str__(self):
        return self.nome_bm
