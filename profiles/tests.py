from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import PhaseHistory, PipelineRoute, PipelineStage, Profile

User = get_user_model()


class PipelineStageModelTests(TestCase):
    def test_migration_seeds_seven_stages_in_order(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        self.assertEqual(len(stages), 7)
        self.assertEqual(stages[0].nome, '1. Perfil criado no AdsPower')
        self.assertEqual(stages[-1].nome, '7. Concluído / Ativo')

    def test_new_profile_defaults_to_first_stage(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        primeira = PipelineStage.objects.order_by('ordem').first()
        self.assertEqual(perfil.fase_atual, primeira)

    def test_stage_with_no_outgoing_route_is_terminal(self):
        stage = PipelineStage.objects.create(nome='Terminal', ordem=100)
        self.assertEqual(list(stage.rotas_saida.all()), [])
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=stage)
        self.assertTrue(perfil.is_concluido)
        self.assertEqual(list(perfil.rotas_disponiveis), [])

    def test_avancar_fase_com_uma_rota(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=101)
        destino = PipelineStage.objects.create(nome='Destino', ordem=102)
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)

        avancou = perfil.avancar_fase(destino)
        perfil.refresh_from_db()

        self.assertTrue(avancou)
        self.assertEqual(perfil.fase_atual, destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()
        self.assertEqual(entrada.fase_nome, 'Destino')
        self.assertEqual(entrada.fase_stage, destino)

    def test_avancar_fase_rejeita_destino_fora_das_rotas_configuradas(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=103)
        destino_valido = PipelineStage.objects.create(nome='Válido', ordem=104)
        destino_invalido = PipelineStage.objects.create(nome='Inválido', ordem=105)
        PipelineRoute.objects.create(origem=origem, destino=destino_valido, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)

        self.assertFalse(perfil.avancar_fase(destino_invalido))
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, origem)

    def test_renomear_fase_nao_altera_historico_existente(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=106)
        destino = PipelineStage.objects.create(nome='Destino', ordem=107)
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)
        perfil.avancar_fase(destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()

        destino.nome = 'Renomeado'
        destino.save(update_fields=['nome'])
        entrada.refresh_from_db()

        self.assertEqual(entrada.fase_nome, 'Destino')
        self.assertEqual(entrada.fase_stage, destino)

    def test_apagar_fase_referenciada_no_historico_zera_fase_stage_mas_preserva_fase_nome(self):
        origem = PipelineStage.objects.create(nome='Origem', ordem=108)
        destino = PipelineStage.objects.create(nome='ParaApagar', ordem=109)
        destino_final = PipelineStage.objects.create(nome='Final', ordem=110)
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)
        perfil.avancar_fase(destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()

        destino.excluir_e_realocar(destino=destino_final)
        entrada.refresh_from_db()

        self.assertEqual(entrada.fase_nome, 'ParaApagar')
        self.assertIsNone(entrada.fase_stage)

    def test_profile_creation_signal_records_initial_history_with_fase_stage(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        entrada = perfil.historico_fases.get()
        self.assertEqual(entrada.fase_nome, perfil.fase_atual.nome)
        self.assertEqual(entrada.fase_stage, perfil.fase_atual)


class PipelineStageDeletionTests(TestCase):
    def test_apagar_fase_sem_perfis_nao_exige_destino(self):
        stage = PipelineStage.objects.create(nome='Vazia', ordem=111)
        stage.excluir_e_realocar()
        self.assertFalse(PipelineStage.objects.filter(pk=stage.pk).exists())

    def test_apagar_fase_com_perfis_sem_destino_levanta_erro(self):
        stage = PipelineStage.objects.create(nome='ComPerfil', ordem=112)
        Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=stage)
        with self.assertRaises(ValueError):
            stage.excluir_e_realocar()

    def test_apagar_fase_com_perfis_move_para_destino_escolhido(self):
        origem = PipelineStage.objects.create(nome='ComPerfil2', ordem=113)
        destino = PipelineStage.objects.create(nome='NovoDestino', ordem=114)
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)

        origem.excluir_e_realocar(destino=destino)
        perfil.refresh_from_db()

        self.assertEqual(perfil.fase_atual, destino)
        entrada = perfil.historico_fases.order_by('-data_hora').first()
        self.assertIn('removida do pipeline', entrada.observacao)

    def test_apagar_ultima_fase_restante_levanta_erro(self):
        PipelineStage.objects.exclude(pk=PipelineStage.objects.order_by('ordem').first().pk).delete()
        ultima = PipelineStage.objects.get()
        with self.assertRaises(ValueError):
            ultima.excluir_e_realocar()

    def test_apagar_fase_remove_rotas_que_a_referenciam(self):
        a = PipelineStage.objects.create(nome='A', ordem=120)
        b = PipelineStage.objects.create(nome='B', ordem=121)
        c = PipelineStage.objects.create(nome='C', ordem=122)
        PipelineRoute.objects.create(origem=a, destino=b, rotulo='Padrão')
        PipelineRoute.objects.create(origem=b, destino=c, rotulo='Padrão')
        b_pk = b.pk

        b.excluir_e_realocar(destino=c)

        self.assertFalse(PipelineRoute.objects.filter(origem_id=b_pk).exists())
        self.assertFalse(PipelineRoute.objects.filter(destino_id=b_pk).exists())


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

    def test_avancar_fase_view_com_uma_rota_nao_exige_destino(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        destino = perfil.fase_atual.rotas_saida.get().destino
        self.client.post(reverse('profiles:profile_advance_phase', args=[perfil.pk]), follow=True)
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, destino)

    def test_avancar_fase_view_com_multiplas_rotas_exige_destino(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        origem = perfil.fase_atual
        alternativa = PipelineStage.objects.create(nome='Alternativa', ordem=200)
        PipelineRoute.objects.create(origem=origem, destino=alternativa, rotulo='Falhou')

        self.client.post(reverse('profiles:profile_advance_phase', args=[perfil.pk]), follow=True)
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, origem, 'sem destino explícito e mais de uma rota, não deve avançar')

        self.client.post(
            reverse('profiles:profile_advance_phase', args=[perfil.pk]),
            {'destino': alternativa.pk},
            follow=True,
        )
        perfil.refresh_from_db()
        self.assertEqual(perfil.fase_atual, alternativa)


class TemplateRenderingPipelineStageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa2', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa2', password='senha-forte-123')

    def test_perfil_detail_mostra_nome_da_fase(self):
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


class PipelineConfigureApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa3', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa3', password='senha-forte-123')

    def test_pipeline_graph_data_retorna_fases_e_rotas(self):
        resp = self.client.get(reverse('profiles:pipeline_graph_data'))
        data = resp.json()
        self.assertEqual(len(data['stages']), 7)
        self.assertEqual(len(data['routes']), 6)
        self.assertIn('rotulo', data['routes'][0])

    def test_criar_fase_via_json(self):
        resp = self.client.post(reverse('profiles:pipeline_stage_create'), {'nome': 'Nova'})
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertEqual(PipelineStage.objects.get(pk=data['stage']['id']).nome, 'Nova')

    def test_criar_fase_sem_nome_retorna_erro_json(self):
        resp = self.client.post(reverse('profiles:pipeline_stage_create'), {'nome': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    def test_renomear_fase_via_json(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        resp = self.client.post(reverse('profiles:pipeline_stage_rename', args=[stage.pk]), {'nome': 'Mudou'})
        self.assertTrue(resp.json()['ok'])
        stage.refresh_from_db()
        self.assertEqual(stage.nome, 'Mudou')

    def test_mover_fase_persiste_posicao(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        resp = self.client.post(
            reverse('profiles:pipeline_stage_move', args=[stage.pk]),
            {'x': 340, 'y': 210},
        )
        self.assertTrue(resp.json()['ok'])
        stage.refresh_from_db()
        self.assertEqual((stage.posicao_x, stage.posicao_y), (340, 210))

    def test_apagar_fase_sem_perfis_via_json(self):
        stage = PipelineStage.objects.create(nome='Solta', ordem=201)
        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[stage.pk]))
        self.assertTrue(resp.json()['ok'])
        self.assertFalse(PipelineStage.objects.filter(pk=stage.pk).exists())

    def test_apagar_fase_com_perfis_sem_destino_retorna_erro_precisa_destino(self):
        stage = PipelineStage.objects.order_by('ordem').first()
        Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=stage)
        resp = self.client.post(reverse('profiles:pipeline_stage_delete', args=[stage.pk]))
        data = resp.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['reason'], 'precisa_destino')

    def test_apagar_fase_com_perfis_e_destino_via_json(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        origem, destino = stages[0], stages[1]
        Profile.objects.create(nome='T', email='t@example.com', senha='x', fase_atual=origem)
        resp = self.client.post(
            reverse('profiles:pipeline_stage_delete', args=[origem.pk]),
            {'destino': destino.pk},
        )
        self.assertTrue(resp.json()['ok'])

    def test_criar_rota_via_json(self):
        stages = list(PipelineStage.objects.order_by('ordem'))
        a, c = stages[0], stages[2]
        resp = self.client.post(reverse('profiles:pipeline_route_create'), {
            'origem': a.pk, 'destino': c.pk, 'rotulo': 'Atalho',
        })
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(PipelineRoute.objects.filter(origem=a, destino=c, rotulo='Atalho').exists())

    def test_apagar_rota_via_json(self):
        rota = PipelineRoute.objects.first()
        resp = self.client.post(reverse('profiles:pipeline_route_delete', args=[rota.pk]))
        self.assertTrue(resp.json()['ok'])
        self.assertFalse(PipelineRoute.objects.filter(pk=rota.pk).exists())

    def test_profile_traversal_data_retorna_caminho_percorrido(self):
        perfil = Profile.objects.create(nome='T', email='t@example.com', senha='x')
        destino = perfil.fase_atual.rotas_saida.get().destino
        perfil.avancar_fase(destino)

        resp = self.client.get(reverse('profiles:profile_traversal_data', args=[perfil.pk]))
        data = resp.json()
        self.assertEqual(len(data['visited_stage_ids']), 2)
        self.assertEqual(data['current_stage_id'], destino.pk)


class PipelineCanvasTemplateTests(TestCase):
    def test_pipeline_configure_carrega_drawflow(self):
        user = User.objects.create_user(username='qa5', password='senha-forte-123')
        client = Client()
        client.login(username='qa5', password='senha-forte-123')
        resp = client.get(reverse('profiles:pipeline_configure'))
        self.assertContains(resp, 'drawflow')
        self.assertContains(resp, reverse('profiles:pipeline_graph_data'))
        self.assertContains(resp, 'integrity=')


class PipelineMapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='qa6', password='senha-forte-123')
        self.client = Client()
        self.client.login(username='qa6', password='senha-forte-123')

    def test_profile_detail_inclui_canvas_de_mapa(self):
        perfil = Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_detail', args=[perfil.pk]))
        self.assertContains(resp, 'pipelineMap')
        self.assertContains(resp, reverse('profiles:profile_traversal_data', args=[perfil.pk]))

    def test_profile_list_tem_botao_ver_mapa(self):
        Profile.objects.create(nome='Teste', email='t@example.com', senha='x')
        resp = self.client.get(reverse('profiles:profile_list'))
        self.assertContains(resp, 'Ver mapa')


class PipelineSidebarLinkTests(TestCase):
    def test_sidebar_tem_link_configurar_pipeline(self):
        user = User.objects.create_user(username='qa4', password='senha-forte-123')
        client = Client()
        client.login(username='qa4', password='senha-forte-123')
        resp = client.get(reverse('profiles:dashboard'))
        self.assertContains(resp, reverse('profiles:pipeline_configure'))
        self.assertContains(resp, 'Configurar pipeline')
