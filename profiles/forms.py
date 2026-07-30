from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import Phase, Profile, ProfileStatus


class StyledAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control', 'autofocus': True})
        self.fields['password'].widget.attrs.update({'class': 'form-control'})


class ProfileForm(forms.ModelForm):
    senha = forms.CharField(
        label='Senha',
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        required=True,
        help_text='Armazenada de forma criptografada no banco de dados.',
    )

    class Meta:
        model = Profile
        fields = [
            'nome',
            'email',
            'senha',
            'tipo_autenticacao',
            'dados_autenticacao',
            'adspower_id',
            'status',
            'responsavel',
            'observacoes',
        ]
        widgets = {
            'dados_autenticacao': forms.Textarea(attrs={'rows': 3}),
            'observacoes': forms.Textarea(attrs={'rows': 4}),
        }
        labels = {
            'adspower_id': 'Perfil/Proxy no AdsPower',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get('class', '')
            field.widget.attrs['class'] = (existing + ' form-control').strip()
        if 'status' in self.fields:
            self.fields['status'].widget.attrs['class'] = 'form-select'
        if 'tipo_autenticacao' in self.fields:
            self.fields['tipo_autenticacao'].widget.attrs['class'] = 'form-select'
        if 'responsavel' in self.fields:
            self.fields['responsavel'].widget.attrs['class'] = 'form-select'

        self._senha_original = None
        if self.instance and self.instance.pk:
            self.fields['senha'].required = False
            self.fields['senha'].help_text = 'Deixe em branco para manter a senha atual.'
            self._senha_original = self.instance.senha

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.instance.pk and not self.cleaned_data.get('senha'):
            profile.senha = self._senha_original
        if commit:
            profile.save()
        return profile


class PhaseAdvanceForm(forms.Form):
    observacao = forms.CharField(
        label='Observação (opcional)',
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'class': 'form-control',
            'placeholder': 'Ex: link da página criada, número vinculado, ID do BM...',
        }),
    )


class ProfileFilterForm(forms.Form):
    q = forms.CharField(
        label='Buscar',
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nome, e-mail ou ID do AdsPower',
        }),
    )
    fase = forms.ChoiceField(
        label='Fase',
        required=False,
        choices=[('', 'Todas as fases')] + list(Phase.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    status = forms.ChoiceField(
        label='Status',
        required=False,
        choices=[('', 'Todos os status')] + list(ProfileStatus.choices),
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
