from .models import Phase


def fases_ordenadas(request):
    return {'fases_ordenadas': Phase.ordered_values()}
