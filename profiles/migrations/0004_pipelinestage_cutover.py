import django.db.models.deletion
from django.db import migrations, models

import profiles.models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0003_seed_pipelinestage_and_backfill'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='profile',
            name='fase_atual',
        ),
        migrations.RenameField(
            model_name='profile',
            old_name='fase_atual_stage',
            new_name='fase_atual',
        ),
        migrations.AlterField(
            model_name='profile',
            name='fase_atual',
            field=models.ForeignKey(
                default=profiles.models.fase_inicial_default,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='perfis',
                to='profiles.pipelinestage',
                verbose_name='Fase atual',
            ),
        ),
        migrations.RemoveField(
            model_name='phasehistory',
            name='fase',
        ),
        migrations.AlterField(
            model_name='phasehistory',
            name='fase_nome',
            field=models.CharField(max_length=150, verbose_name='Fase'),
        ),
    ]
