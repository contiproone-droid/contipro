import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PipelineStage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=150, verbose_name='Nome da fase')),
                ('ordem', models.PositiveIntegerField(unique=True, verbose_name='Ordem')),
            ],
            options={
                'verbose_name': 'Fase do pipeline',
                'verbose_name_plural': 'Fases do pipeline',
                'ordering': ['ordem'],
            },
        ),
        migrations.AddField(
            model_name='profile',
            name='fase_atual_stage',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='perfis',
                to='profiles.pipelinestage',
                verbose_name='Fase atual',
            ),
        ),
        migrations.AddField(
            model_name='phasehistory',
            name='fase_nome',
            field=models.CharField(blank=True, default='', max_length=150, verbose_name='Fase'),
        ),
    ]
