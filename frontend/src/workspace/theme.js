// A stored choice wins; with none, follow the system colour scheme.
export function chooseTheme(stored, systemDark) {
  if (stored === 'dark' || stored === 'light') return stored
  return systemDark ? 'dark' : 'light'
}

export function storedTheme() {
  try {
    return localStorage.getItem('mm-theme')
  } catch {
    return null
  }
}
