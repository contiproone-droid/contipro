from django.db import migrations


def seed_linear_routes(apps, schema_editor):
    PipelineStage = apps.get_model('profiles', 'PipelineStage')
    PipelineRoute = apps.get_model('profiles', 'PipelineRoute')

    stages = list(PipelineStage.objects.order_by('ordem'))
    for origem, destino in zip(stages, stages[1:]):
        PipelineRoute.objects.create(origem=origem, destino=destino, rotulo='Padrão')

    for indice, stage in enumerate(stages):
        stage.posicao_x = indice * 260
        stage.posicao_y = 120
        stage.save(update_fields=['posicao_x', 'posicao_y'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0005_pipelineroute_and_fase_stage'),
    ]

    operations = [
        migrations.RunPython(seed_linear_routes, noop_reverse),
    ]
