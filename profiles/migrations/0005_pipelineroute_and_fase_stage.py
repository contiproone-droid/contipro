import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0004_pipelinestage_cutover'),
    ]

    operations = [
        migrations.AddField(
            model_name='pipelinestage',
            name='posicao_x',
            field=models.IntegerField(default=0, verbose_name='Posição X no canvas'),
        ),
        migrations.AddField(
            model_name='pipelinestage',
            name='posicao_y',
            field=models.IntegerField(default=0, verbose_name='Posição Y no canvas'),
        ),
        migrations.AddField(
            model_name='phasehistory',
            name='fase_stage',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='profiles.pipelinestage',
                verbose_name='Fase (referência)',
            ),
        ),
        migrations.CreateModel(
            name='PipelineRoute',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rotulo', models.CharField(max_length=100, verbose_name='Rótulo')),
                ('destino', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rotas_entrada', to='profiles.pipelinestage', verbose_name='Fase de destino')),
                ('origem', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rotas_saida', to='profiles.pipelinestage', verbose_name='Fase de origem')),
            ],
            options={
                'verbose_name': 'Rota do pipeline',
                'verbose_name_plural': 'Rotas do pipeline',
                'unique_together': {('origem', 'destino')},
            },
        ),
    ]
