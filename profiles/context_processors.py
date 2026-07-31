from .models import PipelineStage


def fases_ordenadas(request):
    return {'fases_ordenadas': PipelineStage.objects.order_by('ordem')}
