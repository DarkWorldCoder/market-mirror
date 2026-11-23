const reports = {
 'summary.json': ['Experiment overview', 'Results'], 'market_report.md': ['Market research report', 'Results'], 'report.md': ['Research narrative', 'Results'],
 'survey.json': ['Buyer survey', 'Buyer research'], 'thought_stream.json': ['Buyer reasoning', 'Buyer research'], 'feed_story.json': ['Social conversations', 'Buyer research'], 'analyst_panel.json': ['Analyst perspectives', 'Buyer research'], 'questionnaire.json': ['Questionnaire responses', 'Buyer research'], 'focus_group.json': ['Focus group discussion', 'Buyer research'],
 'feed_test.json': ['Ad creative comparison', 'Advertising'], 'feed_test_creatives.csv': ['Creative performance', 'Advertising'], 'feed_test_sessions.csv': ['Individual feed sessions', 'Advertising'], 'ad_patterns.json': ['Creative patterns', 'Advertising'], 'ideas.json': ['Creative ideas', 'Advertising'],
 'pitch.json': ['Sales pitch reactions', 'Strategy'], 'email_test.json': ['Email campaign results', 'Strategy'], 'choice_test.json': ['Preference study', 'Strategy'], 'campaign_plan.json': ['Campaign plan', 'Strategy'],
 'config.json': ['Audience profiles', 'Audience'], 'graph.json': ['Audience network', 'Audience'], 'agent_stats.json': ['Persona activity', 'Activity'], 'timeline.json': ['Activity over time', 'Activity'], 'actions.json': ['Recorded actions', 'Activity'],
 'backtest.json': ['Comparison with real results', 'Validation'], 'calibration.json': ['Calibration results', 'Validation'], 'real_check.csv': ['Questions for real customers', 'Validation'],
 'dashboard.html': ['Standalone dashboard', 'Results'], 'disclosure.md': ['Study methodology', 'Methodology'], 'usage.json': ['Model usage', 'Usage'], 'run_manifest.json': ['Run metadata', 'Advanced'], 'ontology.json': ['Graph schema', 'Advanced'],
}
export const readableLabel = value => String(value).replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ').replace(/\b(?:id|ids|api|crm|csv|json|url|llm|ssr|ctr|cpa|roas)\b/gi, word => word.toUpperCase()).replace(/^./, char => char.toUpperCase())
export function reportInfo(file) {
 const known = reports[file]
 const title = known?.[0] || readableLabel(String(file).replace(/\.[^.]+$/, '').replaceAll('-', ' '))
 const category = known?.[1] || (/^(posts|comments)_/.test(file) ? 'Buyer research' : /usage|cost|spend/.test(file) ? 'Usage' : /manifest|config|log|ontology|provenance/.test(file) ? 'Advanced' : 'Other reports')
 return { file, title, category }
}
export function preferredReport(files = []) { return ['summary.json', 'market_report.md', 'report.md', 'survey.json', 'feed_test.json'].find(file => files.includes(file)) || files.find(file => reportInfo(file).category !== 'Advanced') || files[0] || '' }
export function tableRows(value) {
 if (!Array.isArray(value) || !value.length) return null
 if (value.every(row => Array.isArray(row) && row.length === 2 && typeof row[0] === 'string' && typeof row[1] === 'number')) return value.map(([label, count]) => ({ label, count }))
 return value.every(row => row && typeof row === 'object' && !Array.isArray(row)) ? value : null
}
