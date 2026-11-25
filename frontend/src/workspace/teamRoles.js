// Changing your own role, or demoting an owner, can remove the last way back;
// other role changes apply immediately.
export function roleChangeNeedsConfirmation(member, nextRole, you) {
  if (!member) return false
  if (member.id === you) return true
  return member.role === 'owner' && nextRole !== 'owner'
}
