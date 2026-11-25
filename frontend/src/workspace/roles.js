// The workspace roles, with the same label and one-line explanation everywhere
// a person picks one.
export const ROLES = ['owner', 'editor', 'viewer']

export function roleLabel(role) {
  return role ? role.charAt(0).toUpperCase() + role.slice(1) : ''
}

export function roleHint(role) {
  return {
    owner: 'Owner: manage the workspace, members, invitations and every chat.',
    editor: 'Editor: create and edit chats, projects and runs.',
    viewer: 'Viewer: read chats, projects and runs.',
  }[role] || ''
}
