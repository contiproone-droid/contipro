from django.db import migrations

FASES_INICIAIS = [
    (1, 'perfil_criado', '1. Perfil criado no AdsPower'),
    (2, 'login_facebook', '2. Login/acesso ao perfil no Facebook'),
    (3, 'verificacao_pagina', '3. Verificação de página do Facebook'),
    (4, 'criacao_pagina', '4. Criação da página'),
    (5, 'vinculo_whatsapp', '5. Vínculo da conta do WhatsApp'),
    (6, 'geracao_bm', '6. Geração do Business Manager'),
    (7, 'concluido', '7. Concluído / Ativo'),
]


def seed_and_backfill(apps, schema_editor):
    PipelineStage = apps.get_model('profiles', 'PipelineStage')
    Profile = apps.get_model('profiles', 'Profile')
    PhaseHistory = apps.get_model('profiles', 'PhaseHistory')

    stage_by_code = {}
    for ordem, codigo, nome in FASES_INICIAIS:
        stage_by_code[codigo] = PipelineStage.objects.create(nome=nome, ordem=ordem)

    for perfil in Profile.objects.all():
        stage = stage_by_code.get(perfil.fase_atual)
        if stage is not None:
            perfil.fase_atual_stage = stage
            perfil.save(update_fields=['fase_atual_stage'])

    for entrada in PhaseHistory.objects.all():
        stage = stage_by_code.get(entrada.fase)
        entrada.fase_nome = stage.nome if stage is not None else entrada.fase
        entrada.save(update_fields=['fase_nome'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0002_pipelinestage_add_temp_fields'),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, noop_reverse),
    ]
