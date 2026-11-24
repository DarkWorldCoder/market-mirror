import { reactive, ref } from 'vue'
import { api } from './api.js'
// Discovery describes real engine capabilities. Selecting a feature prepares a request;
// it never implies that an experiment has run or a data account is connected.
const feature = (id, label, group, description, prompt, extra = {}) => ({ id, command: `/${id}`, label, group, description, prompt, mode: 'model', ...extra })
export const featureCatalog = reactive([
  feature('experiment', 'New experiment', 'Workspace', 'Open guided setup for a marketing experiment.', '', { action: 'experiment', mode: 'configuration', aliases: ['new-experiment'] }),
  feature('analyze', 'Analyze a website', 'Workspace', 'Capture a page and analyze it with your chosen model or team.', '', { action: 'analyze', mode: 'model', aliases: ['browser', 'web-analysis'] }),
  feature('project', 'Create a project', 'Workspace', 'Turn a brief into a saved project.', 'Help me create a project. Ask for its name, product, audience, and decision.', { action: 'project', mode: 'configuration', aliases: ['upload', 'understand'] }),
  feature('runs', 'Find saved reports', 'Workspace', 'Search previous runs and their artifacts.', 'Show my saved runs and reports.', { action: 'runs', mode: 'read-only', aliases: ['list', 'results', 'export'] }),
  feature('settings', 'Workspace settings', 'Workspace', 'Configure persona memory and the Jev decision engine.', '', { action: 'settings', mode: 'configuration', aliases: ['memory', 'jev', 'configure'] }),
  feature('models', 'Choose a model', 'Workspace', 'See available providers and change the chat model.', '', { action: 'models', mode: 'configuration', aliases: ['provider', 'setup'] }),
  feature('connectors', 'Connect data and tools', 'Workspace', 'Add evidence, analytics exports, and model providers.', '', { action: 'connectors', mode: 'configuration', aliases: ['connections', 'integrations'] }),
  feature('search', 'Search run evidence', 'Workspace', 'Find local evidence with ranked text search.', 'Search the selected run for evidence about ', { mode: 'read-only' }),
  feature('health', 'Check local connection', 'Workspace', 'Inspect backend and provider readiness.', 'Check the local service and provider status.', { mode: 'read-only', aliases: ['doctor', 'status'] }),
  feature('report', 'Explore the market report', 'Workspace', 'Read saved findings, decisions, and downloadable artifacts.', 'Summarize the selected run’s saved market report, cite the evidence, and show available artifacts.', { mode: 'read-only', aliases: ['market-report', 'chat', 'export'] }),
  feature('simulation', 'Inspect simulation progress', 'Workspace', 'Review project, graph, agents, and simulation status.', 'Show the selected simulation’s project, graph preparation, agents, progress, and available results.', { mode: 'read-only', aliases: ['build-graph', 'create-sim', 'prepare', 'start', 'wait', 'stop', 'close-env', 'live', 'start_live', 'job_status'] }),
  feature('seed-check', 'Check research evidence', 'Buyer research', 'Inspect seed quality and contact details before use.', 'Help me check my research seed for evidence quality and contact details before using it. Ask me to attach the source.', { mode: 'read-only' }),
  feature('market-test', 'Test a marketing decision', 'Buyer research', 'Personas, feed tests, surveys, and analyst review.', 'Help me design a market test. Clarify the decision, audience, alternatives, evidence, and budget before running it.', { aliases: ['market_test', 'run', 'quickstart'] }),
  feature('research', 'Research buyer feedback', 'Buyer research', 'Gather cited public feedback for a decision.', 'Research public buyer feedback for this product and cite the sources: '),
  feature('intake', 'Build personas from evidence', 'Buyer research', 'Use CRM, reviews, interviews, or transcripts.', 'Help me build evidence-grounded personas from my customer files. Ask me to attach the evidence.'),
  feature('analytics', 'Analyze GA4 or PostHog audiences', 'Buyer research', 'Use aggregate analytics exports to ground personas.', 'Help me analyze an aggregate GA4 or PostHog export and build an audience brief. Ask for a CSV or JSON export and preserve its provenance.', { aliases: ['ga4', 'posthog', 'analytics-audience'] }),
  feature('personas', 'Inspect buyer personas', 'Buyer research', 'Review profiles and their evidence.', 'Show the personas and evidence available in the selected run.', { mode: 'read-only', aliases: ['profiles'] }),
  feature('ask', 'Ask the buyers', 'Buyer research', 'Question saved personas after a run.', 'Ask the saved buyer personas this question: ', { aliases: ['ask_buyers', 'interview'] }),
  feature('focus-group', 'Run a focus group', 'Buyer research', 'Moderated discussion between simulated buyers.', 'Help me prepare a focus group with the selected personas. The topic is '),
  feature('survey', 'Survey the audience', 'Buyer research', 'Structured reactions and response estimates.', 'Help me design a buyer survey for ', { aliases: ['survey-estimate', 'ssr', 'affect-ssr'] }),
  feature('questionnaire', 'Create a questionnaire', 'Buyer research', 'Reusable questions with structured responses.', 'Help me create a questionnaire for this research question: '),
  feature('choice-test', 'Compare preferences and pricing', 'Buyer research', 'MaxDiff, conjoint, and Gabor–Granger studies.', 'Help me choose and design a MaxDiff, conjoint, or Gabor–Granger study for '),
  feature('context', 'Update live buyer context', 'Buyer research', 'Supply new information to a running simulation.', 'Help me add new context to the selected simulation. Explain which personas receive it before applying it: ', { aliases: ['push_context', 'events'] }),
  feature('thoughts', 'Explore buyer reasoning', 'Buyer research', 'Inspect recorded persona thought streams.', 'Show the recorded buyer reasoning and its limitations in the selected run.', { mode: 'read-only', aliases: ['thought-stream'] }),
  feature('ads-import', 'Import advertising results', 'Advertising', 'Normalize Meta or Google Ads CSV and JSON exports.', 'Help me import a Meta or Google Ads export, validate its rows, and compare creative performance. Ask me to attach the export.'),
  feature('actuals', 'Import real performance', 'Advertising', 'Preserve provenance for ads, email, web, CRM, or surveys.', 'Help me import real performance data. Ask for my CSV or JSON file and identify row-level validation errors.', { aliases: ['actuals-import'] }),
  feature('ad-patterns', 'Find winning creative patterns', 'Advertising', 'Analyze creative dimensions against observed results.', 'Analyze patterns in my advertising creatives and results. Ask for the creatives and actual performance evidence.'),
  feature('creative-check', 'Review an image or video ad', 'Advertising', 'Evaluate actual creative assets before a test.', 'Help me review this image or video creative. Ask for the asset, audience, placement, and goal.'),
  feature('feed-test', 'Test ads in a simulated feed', 'Advertising', 'Compare creative reactions and choice.', 'Help me prepare a simulated feed test. Ask for the creative variants and target audience.', { aliases: ['feedtest'] }),
  feature('ideas', 'Generate evidence-led ad ideas', 'Advertising', 'Use actual results or a saved research run.', 'Generate ad ideas grounded in the selected run or my actual ad results. Cite the evidence behind each idea.'),
  feature('captions', 'Draft creative captions', 'Advertising', 'Generate captions for a defined audience and goal.', 'Help me draft captions. Ask for the product, audience, platform, creative, and goal.'),
  feature('backtest', 'Compare simulation with real ads', 'Advertising', 'Check ranking, winner match, and calibration.', 'Help me compare a saved simulated feed test against real ad results. Ask for matching variants and their actual outcomes.'),
  feature('campaign', 'Plan a campaign', 'Strategy', 'Create an evidence-led plan and runnable test specs.', 'Build a campaign plan from my product, audience, evidence, goal, and constraints. Include testable alternatives.', { aliases: ['campaign-plan'] }),
  feature('test', 'Design a controlled test', 'Strategy', 'Ad, message, price, offer, naming, landing, and launch tests.', 'Help me design a test. Ask what decision I need to make, which variants to compare, and how success will be measured.', { aliases: ['run_test', 'ad', 'message', 'price', 'offer', 'positioning', 'naming', 'landing', 'launch', 'pitch', 'email', 'creator_post', 'channel_mix'] }),
  feature('website', 'Test a website journey', 'Strategy', 'Observe browser actions and explicit goal checks.', 'Help me prepare a website test. Ask for the URL, audience, journey, and explicit success checks before starting.', { aliases: ['website-test', 'landing'] }),
  feature('email', 'Test an email sequence', 'Strategy', 'Compare email messages and simulated buyer reactions.', 'Help me test an email sequence. Ask for the emails, audience, and desired action.', { aliases: ['emailtest', 'email-test'] }),
  feature('pitch', 'Stress-test a sales pitch', 'Strategy', 'Identify reactions, objections, and weak claims.', 'Help me stress-test this pitch with the target buyers: '),
  feature('panel', 'Get an analyst panel review', 'Strategy', 'Independent analyst lenses on the same evidence.', 'Review the selected run with independent analyst perspectives and cite the evidence.', { aliases: ['analyst-panel'] }),
  feature('objections', 'Explore buyer objections', 'Strategy', 'Find friction, concerns, and unanswered questions.', 'Help me identify buyer objections to this offer: ', { aliases: ['objection-check'] }),
  ...[
    ['committee', 'Map the buying committee', 'Identify stakeholders, influence, and purchase blockers.'],
    ['creative', 'Evaluate a creative concept', 'Review a supplied creative or offer with buyer context.'],
    ['battlecard', 'Build a sales battlecard', 'Compare alternatives using available evidence.'],
    ['journey', 'Map the buyer journey', 'Identify stages, friction, and decision moments.'],
    ['pricing', 'Explore pricing reactions', 'Examine value, willingness, and objections.'],
    ['competitors', 'Analyze competitors', 'Compare positioning and buyer alternatives.'],
    ['teardown', 'Review a landing page', 'Inspect the promise, proof, and conversion path.'],
    ['roleplay', 'Practice a buyer conversation', 'Roleplay a supplied opening message.'],
    ['whatif', 'Explore a decision scenario', 'Change assumptions and inspect directional effects.'],
    ['personalize', 'Personalize buyer messaging', 'Adapt messaging to evidence-grounded segments.'],
    ['geo', 'Review AI search visibility', 'Assess discovery and citation readiness.'],
    ['voc', 'Ground messaging in customer language', 'Find recurring language from supplied evidence.'],
    ['cascade', 'Explore word-of-mouth effects', 'Inspect simulated sharing and influence.'],
  ].map(([id, label, description]) => feature(id, label, 'Go to market', description, `Help me ${label.toLowerCase()} for my product. Ask for the necessary evidence and inputs.`, { engine: `gtm:${id}` })),
  feature('gtm-suite', 'Run a go-to-market review', 'Go to market', 'Coordinate the engine’s strategy review modules.', 'Help me scope a go-to-market review, choose relevant modules, and estimate the work before running it.'),
  feature('predict', 'Explore outcome ranges', 'Validation', 'Directional intervals and a 90-day forecast.', 'Help me interpret outcome ranges and forecast assumptions for the selected run. Clearly label simulated estimates.'),
  feature('forecast', 'Track forecasts against outcomes', 'Validation', 'Lock predictions and score observed outcomes.', 'Help me create or score a forecast. Ask for the prediction, target date, metric, and actual evidence.'),
  feature('study', 'Run a repeated study', 'Validation', 'Repeat scenarios across seeds to inspect stability.', 'Help me design a repeated study across scenarios and seeds. Explain cost and evaluation before running.'),
  feature('calibrate', 'Calibrate against real evidence', 'Validation', 'Use matched simulated and observed results.', 'Help me calibrate this run against matched real outcomes. Ask for the paired evidence.'),
  feature('holdout', 'Evaluate held-out experiments', 'Validation', 'Compare against a training-mean baseline.', 'Help me design a held-out backtest with independent experiments and a training-mean baseline.', { aliases: ['holdout-backtest'] }),
  feature('split', 'Create a real-data holdout', 'Validation', 'Separate training and evaluation evidence.', 'Help me split real evidence into training and holdout partitions before testing.', { aliases: ['real-split'] }),
  feature('benchmark', 'Run a human-data benchmark', 'Validation', 'Compare against supported open datasets.', 'Help me choose a supported human-data benchmark and explain what it can validate.', { aliases: ['bench'] }),
  feature('compare', 'Compare model providers', 'Validation', 'Evaluate the same task across available providers.', 'Help me design a fair comparison across my configured model providers.'),
  feature('spend', 'Review the simulation spend cap', 'Validation', 'Inspect or configure run spending limits.', 'Show the current simulation spend cap and explain any proposed changes before applying them.', { aliases: ['spend-cap'], mode: 'configuration' }),
])

const builtInFeatures = [...featureCatalog]
export const featureGroups = reactive([...new Set(featureCatalog.map(item => item.group))])
export const customSkillError = ref('')
let customRequest = null
export function loadCustomSkills(force = false) {
  if (customRequest) return force ? customRequest.catch(() => {}).then(() => loadCustomSkills()) : customRequest
  customRequest = (async () => {
    try {
      const skills = await api('/api/workspace/skills')
      const custom = skills.map(skill => {
        const slug = skill.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 35) || 'skill'
        return { id: `custom-${skill.id}`, skillId: skill.id, command: `/custom-${slug}-${skill.id.slice(-6)}`, label: skill.name, group: skill.group, description: skill.description, prompt: skill.instructions, instructions: skill.instructions, sourceUrl: skill.source_url, mode: 'model', custom: true, aliases: ['custom', skill.name] }
      })
      featureCatalog.splice(0, featureCatalog.length, ...builtInFeatures, ...custom)
      featureGroups.splice(0, featureGroups.length, ...new Set(featureCatalog.map(item => item.group)))
      customSkillError.value = ''
      return skills
    } catch (error) { customSkillError.value = error.message; throw error }
    finally { customRequest = null }
  })()
  return customRequest
}
export function searchFeatures(query = '') {
  const words = query.replace(/^\//, '').trim().toLowerCase().split(/\s+/).filter(Boolean)
  return featureCatalog.filter(item => words.every(word => [item.id, item.command, item.label, item.group, item.description, ...(item.aliases || [])].join(' ').toLowerCase().includes(word)))
}
