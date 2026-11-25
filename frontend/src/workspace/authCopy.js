// Copy for the sign-in page, kept pure so the invite-only/closed distinction
// is testable without mounting the view.
export function canSignUp(signups, hasInvite, firstAccount) {
  return Boolean(hasInvite) || firstAccount || signups === 'open'
}

export function signupSubheading(signups) {
  if (signups === 'invite') return 'Sign-up is invite-only. Open the invitation link from a workspace owner.'
  if (signups === 'closed') return 'Sign-ups are closed on this server. Ask a workspace owner for an account.'
  return 'Start a workspace for your team.'
}
