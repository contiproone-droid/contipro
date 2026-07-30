from django import template

register = template.Library()

BADGE_COLORS = {
    'ativo': 'success',
    'criada': 'success',
    'vinculado': 'success',
    'concluido': 'success',
    'pendente': 'warning',
    'suspenso': 'warning',
    'restrito': 'warning',
    'pausado': 'secondary',
    'banido': 'danger',
    'falhou': 'danger',
}


@register.filter
def badge_color(value):
    return BADGE_COLORS.get(value, 'secondary')
