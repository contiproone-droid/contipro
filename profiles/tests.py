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
