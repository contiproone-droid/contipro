from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PhaseHistory, Profile


@receiver(post_save, sender=Profile)
def registrar_fase_inicial(sender, instance, created, **kwargs):
    """Ao criar um Profile, registra a fase inicial no histórico de auditoria."""
    if created:
        PhaseHistory.objects.create(
            perfil=instance,
            fase_nome=instance.fase_atual.nome,
            fase_stage=instance.fase_atual,
            usuario=instance.responsavel,
            observacao='Perfil criado.',
        )
