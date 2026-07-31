from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import PhaseHistory, PipelineStage, Profile

User = get_user_model()


class PipelineStageModelTests(TestCase):
    def test_migration_seeds_seven_stages_in_order(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        self.assertEqual(len(stages), 7)
        self.assertEqual(stages[0].nome, '1. Perfil criado no AdsPower')
        self.assertEqual(stages[-1].nome, '7. Concluído / Ativo')
        self.assertEqual([s.ordem for s in stages], [1, 2, 3, 4, 5, 6, 7])

    def test_new_profile_defaults_to_first_stage(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        primeira = PipelineStage.objects.order_by('ordem').first()
        self.assertEqual(perfil.fase_atual, primeira)

    def test_avancar_fase_usa_ordem_dinamica(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        segunda = PipelineStage.objects.order_by('ordem')[1]
        avancou = perfil.avancar_fase(observacao='obs')
        perfil.refresh_from_db()
        self.assertTrue(avancou)
        self.assertEqual(perfil.fase_atual, segunda)

    def test_is_concluido_true_na_ultima_fase(self):
        ultima = PipelineStage.objects.order_by('-ordem').first()
        perfil = Profile.objects.create(
            nome='Teste', email='t@example.com', senha='x', fase_atual=ultima,
        )
        self.assertTrue(perfil.is_concluido)
        self.assertIsNone(perfil.proxima_fase)
        self.assertFalse(perfil.avancar_fase())

    def test_renomear_fase_nao_altera_historico_existente(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        perfil.avancar_fase()
        entrada = perfil.historico_fases.order_by('-data_hora').first()
        nome_original = entrada.fase_nome

        segunda = PipelineStage.objects.order_by('ordem')[1]
        segunda.nome = 'Nome renomeado'
        segunda.save(update_fields=['nome'])

        entrada.refresh_from_db()
        self.assertEqual(entrada.fase_nome, nome_original)
        self.assertNotEqual(entrada.fase_nome, 'Nome renomeado')

    def test_profile_creation_signal_records_initial_history_with_fase_nome(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        entrada = perfil.historico_fases.get()
        self.assertEqual(entrada.fase_nome, perfil.fase_atual.nome)


class ProfileViewsPipelineStageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa', password='senha-forte-123')

    def test_filtro_por_fase_na_listagem(self):
        segunda = PipelineStage.objects.order_by('ordem')[1]
        Profile.objects.create(nome='Alvo', email='a@example.com', senha='x', fase_atual=segunda)
        Profile.objects.create(nome='Outro', email='b@example.com', senha='x')

        resp = self.client.get(reverse('profiles:profile_list'), {'fase': segunda.pk})
        self.assertContains(resp, 'Alvo')
        self.assertNotContains(resp, 'Outro')

    def test_api_dashboard_data_inclui_ordem_por_fase(self):
        resp = self.client.get(reverse('profiles:api_dashboard_data'))
        data = resp.json()
        self.assertEqual(len(data['funil']), 7)
        self.assertEqual(data['funil'][0]['ordem'], 1)
        self.assertEqual(data['funil'][-1]['ordem'], 7)

    def test_dashboard_conta_concluidos_pela_ultima_fase(self):
        ultima = PipelineStage.objects.order_by('-ordem').first()
        Profile.objects.create(nome='Feito', email='f@example.com', senha='x', fase_atual=ultima)
        resp = self.client.get(reverse('profiles:dashboard'))
        self.assertEqual(resp.context['concluidos_total'], 1)

    def test_avancar_fase_view_usa_nome_da_fase(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.post(reverse('profiles:profile_advance_phase', args=[perfil.pk]), follow=True)
        self.assertContains(resp, 'Login/acesso ao perfil no Facebook')


class TemplateRenderingPipelineStageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa2', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa2', password='senha-forte-123')

    def test_pipeline_track_renderiza_nome_da_fase(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'Perfil criado no AdsPower')

    def test_advance_modal_usa_nome_da_proxima_fase(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'Login/acesso ao perfil no Facebook')

    def test_historico_de_fases_mostra_fase_nome(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'Perfil criado.')


class PipelineConfigureViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa3', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa3', password='senha-forte-123')

    def test_pipeline_configure_lista_fases_na_ordem(self):
        resp = self.client.get(reverse('profiles:pipeline_configure'))
        self.assertEqual(resp.status_code, 200)
        stages = list(resp.context['stages'])
        self.assertEqual([s.ordem for s in stages], list(range(1, 8)))

    def test_criar_fase_adiciona_na_ultima_posicao(self):
        self.client.post(reverse('profiles:pipeline_stage_create'), {'nome': 'Nova fase'})
        nova = PipelineStage.objects.get(nome='Nova fase')
        self.assertEqual(nova.ordem, 8)

    def test_renomear_fase_via_post(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        self.client.post(reverse('profiles:pipeline_stage_rename', args=[stage.pk]), {'nome': 'Renomeada'})
        stage.refresh_from_db()
        self.assertEqual(stage.nome, 'Renomeada')

    def test_apagar_fase_do_meio_move_perfis_e_redireciona(self):
        segunda = PipelineStage.objects.order_by('ordem')[1]
        perfil = Profile.objects.create(nome='Alvo', email='a@example.com', senha='x', fase_atual=segunda)

        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[segunda.pk]), follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PipelineStage.objects.filter(pk=segunda.pk).exists())
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual.ordem, 1)

    def test_apagar_ultima_fase_restante_mostra_erro(self):
        PipelineStage.objects.exclude(pk=PipelineStage.objects.order_by('ordem').first().pk).delete()
        ultima = PipelineStage.objects.get()

        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[ultima.pk]), follow=True)

        self.assertTrue(PipelineStage.objects.filter(pk=ultima.pk).exists())
        messages_list = list(resp.context['messages'])
        self.assertTrue(any('última fase' in str(m) for m in messages_list))

    def test_reordenar_via_post_persiste_nova_ordem(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        nova_ordem_pks = [s.pk for s in reversed(stages)]

        resp = self.client.post(reverse('profiles:pipeline_stage_reorder'), {'pk': nova_ordem_pks})

        self.assertEqual(resp.status_code, 200)
        primeira = PipelineStage.objects.order_by('ordem').first()
        self.assertEqual(primeira.pk, nova_ordem_pks[0])


class PipelineSidebarLinkTests(TestCase):
    def test_sidebar_tem_link_configurar_pipeline(self):
        user = User.objects.create_user(username='qa4', password='senha-forte-123')
        client = Client()
        client.login(username='qa4', password='senha-forte-123')
        resp = client.get(reverse('profiles:dashboard'))
        self.assertContains(resp, reverse('profiles:pipeline_configure'))
        self.assertContains(resp, 'Configurar pipeline')
