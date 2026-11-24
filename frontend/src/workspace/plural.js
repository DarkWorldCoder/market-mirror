// English plural selection through Intl.PluralRules. The shell is not
// translated yet; when it is, these calls become vue-i18n plural messages.
const rules = new Intl.PluralRules('en')

export function plural(n, forms) {
  const form = forms[rules.select(n)] ?? forms.other
  return typeof form === 'function' ? form() : form
}
