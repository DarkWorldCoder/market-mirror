// Field rules for the guided comparison set up inside the chat. They mirror what /api/workflows accepts
// (backend/app/services/workflows.py normalize + validate_ready), so a person sees a problem before saving.

export const OTHER = '__other__'
export const LIMITS = {
  name: 120, product: 5000, facts: 24000, source_url: 2000, audience: 1500, country: 120, language: 80,
  label: 80, text: 8000, claim_evidence: 4000, currency: 8, peopleMin: 4, peopleMax: 60, budgetMax: 100000000
}
export const AUDIENCE_SIZES = [8, 20, 40, 60]
export const PLATFORMS = [
  { id: 'instagram', label: 'Instagram' }, { id: 'facebook', label: 'Facebook' }, { id: 'tiktok', label: 'TikTok' },
  { id: 'linkedin', label: 'LinkedIn' }, { id: 'x', label: 'X' }, { id: 'reddit', label: 'Reddit' }
]
export const COUNTRIES = [
  'United States', 'United Kingdom', 'Canada', 'Australia', 'New Zealand', 'Ireland', 'India', 'Nepal', 'Pakistan',
  'Bangladesh', 'Sri Lanka', 'Singapore', 'Malaysia', 'Indonesia', 'Philippines', 'Vietnam', 'Thailand', 'Japan',
  'South Korea', 'China', 'United Arab Emirates', 'Saudi Arabia', 'Egypt', 'Nigeria', 'Kenya', 'South Africa',
  'Germany', 'France', 'Spain', 'Italy', 'Netherlands', 'Sweden', 'Poland', 'Turkey', 'Brazil', 'Mexico',
  'Argentina', 'Colombia', 'Chile'
]
export const LANGUAGES = [
  'English', 'Spanish', 'French', 'German', 'Portuguese', 'Italian', 'Dutch', 'Hindi', 'Nepali', 'Bengali', 'Urdu',
  'Arabic', 'Chinese', 'Japanese', 'Korean', 'Indonesian', 'Vietnamese', 'Thai', 'Turkish', 'Polish', 'Swedish'
]
export const CURRENCIES = ['USD', 'EUR', 'GBP', 'INR', 'NPR', 'AUD', 'CAD', 'SGD', 'AED', 'JPY', 'BRL', 'MXN']

// A select shows a listed value, "another" for a saved value that is not listed, or nothing yet.
export function choiceOf(value, options) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return options.includes(text) ? text : OTHER
}

export function isWebUrl(value) {
  const text = String(value ?? '').trim()
  if (!text) return false
  try {
    const url = new URL(text)
    return (url.protocol === 'http:' || url.protocol === 'https:') && !!url.hostname && !url.username && !url.password
  } catch {
    return false
  }
}

const blank = value => !String(value ?? '').trim()
const tooLong = (value, max) => String(value ?? '').length > max

export function briefErrors(inputs = {}) {
  const errors = {}
  if (blank(inputs.name)) errors.name = 'Add the product or business name.'
  else if (tooLong(inputs.name, LIMITS.name)) errors.name = `Keep the name under ${LIMITS.name} characters.`
  if (blank(inputs.product)) errors.product = 'Say what it does and who it is for.'
  else if (tooLong(inputs.product, LIMITS.product)) errors.product = `Keep this under ${LIMITS.product} characters.`
  if (!blank(inputs.source_url) && !isWebUrl(inputs.source_url)) errors.source_url = 'Enter a full web address starting with https://'
  if (tooLong(inputs.facts, LIMITS.facts)) errors.facts = `Keep the details under ${LIMITS.facts} characters.`
  return errors
}

export function ideasErrors(inputs = {}) {
  const errors = {}
  const variants = Array.isArray(inputs.variants) ? inputs.variants : []
  variants.forEach((variant, index) => {
    if (blank(variant?.label)) errors[`label${index}`] = 'Give this version a short name.'
    if (blank(variant?.text)) errors[`text${index}`] = `Add version ${'AB'[index]}.`
    else if (tooLong(variant.text, LIMITS.text)) errors[`text${index}`] = `Keep this under ${LIMITS.text} characters.`
  })
  if (variants.length === 2 && !blank(variants[0]?.text) && variants[0].text.trim() === String(variants[1]?.text ?? '').trim())
    errors.text1 = 'The two versions are identical. Change one of them.'
  if (blank(inputs.audience)) errors.audience = 'Describe who should consider this.'
  if (blank(inputs.country)) errors.country = 'Choose a country or market.'
  if (blank(inputs.language)) errors.language = 'Choose a language.'
  const people = inputs.people
  if (people === '' || people === null || people === undefined || !Number.isInteger(Number(people)))
    errors.people = `Enter a whole number from ${LIMITS.peopleMin} to ${LIMITS.peopleMax}.`
  else if (Number(people) < LIMITS.peopleMin || Number(people) > LIMITS.peopleMax)
    errors.people = `Choose between ${LIMITS.peopleMin} and ${LIMITS.peopleMax} people.`
  if (!PLATFORMS.some(p => p.id === inputs.platform)) errors.platform = 'Choose a channel.'
  const budget = inputs.ad_budget
  if (budget !== '' && budget !== null && budget !== undefined) {
    const amount = Number(budget)
    if (!Number.isFinite(amount) || amount < 0) errors.ad_budget = 'Enter 0 or more, or leave it empty.'
    else if (amount > LIMITS.budgetMax) errors.ad_budget = 'That budget is too large.'
  }
  return errors
}
