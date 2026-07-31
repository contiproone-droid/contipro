import django.db.models.deletion
from django.db import migrations, models


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
            # default=1 (not the live profiles.models.fase_inicial_default) on purpose:
            # migration 0003 already backfilled every row, so this value is never actually
            # applied to data — but Django's SQLite table-remake unconditionally evaluates
            # the default, and a reference to the *current* callable would query whatever
            # columns PipelineStage has *today*, not the columns that existed at this point
            # in migration history, breaking any fresh replay from zero (tests, new envs)
            # once later migrations add fields to PipelineStage.
            field=models.ForeignKey(
                default=1,
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
