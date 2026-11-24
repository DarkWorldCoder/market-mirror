import test from 'node:test'
import assert from 'node:assert/strict'
import {
  activityLevel, barWidths, calendarWeeks, dayKey, dayLabel, gradeCounts, gradeText, intentRows, liveProgress, liveStage,
  namesOnDay, normalizeInsights, outcomeText, pct, pollable, position, stillRunning, trustNudge, usd
} from '../overviewInsights.js'

test('a missing or malformed payload becomes a complete empty one', () => {
  const empty = normalizeInsights(null)
  assert.deepEqual(empty.geography.countries, [])
  assert.equal(empty.spend.total_usd, 0)
  assert.deepEqual(empty.decisions, { go: 0, iterate: 0, no_go: 0, unrecorded: 0 })
  const odd = normalizeInsights({ intent: 'x', geography: { countries: 'nope', people_with_country: 3 }, decisions: { go: 2 }, spend: { total_usd: 'a' } })
  assert.deepEqual(odd.intent, [])
  assert.deepEqual(odd.geography.countries, [])
  assert.equal(odd.geography.people_with_country, 3)
  assert.equal(odd.decisions.go, 2)
  assert.equal(odd.decisions.no_go, 0)
  assert.equal(odd.spend.total_usd, 0)
})

test('activity levels scale with the busiest day', () => {
  assert.equal(activityLevel(0, 5), 0)
  assert.equal(activityLevel(1, 1), 4)
  assert.equal(activityLevel(1, 8), 1)
  assert.equal(activityLevel(4, 8), 2)
  assert.equal(activityLevel(8, 8), 4)
  assert.equal(activityLevel(undefined, 8), 0)
})

test('the calendar ends this week, starts on a Sunday and places runs on their day', () => {
  const end = new Date(2026, 10, 24)            // Tuesday 24 Nov 2026
  const cal = calendarWeeks([{ date: '2026-11-20', count: 2, runs: ['a', 'b'] }, { date: '2026-11-24', count: 1, runs: ['c'] },
    { date: '2026-01-02', count: 5, runs: [] }], end, 26, 'en-US')
  assert.equal(cal.weeks.length, 26)
  assert.ok(cal.weeks.every((w) => w.length === 7))
  const first = cal.weeks[0][0]
  const [y, m, d] = first.date.split('-').map(Number)
  assert.equal(new Date(y, m - 1, d).getDay(), 0)
  const cells = cal.weeks.flat()
  const fri = cells.find((c) => c.date === '2026-11-20')
  assert.deepEqual([fri.count, fri.level, fri.runs], [2, 4, ['a', 'b']])
  assert.equal(cells.find((c) => c.date === '2026-11-24').level, 2)
  assert.ok(cells.find((c) => c.date === '2026-11-25').future)
  assert.equal(cal.shown, 3)
  assert.equal(cal.earlier, 5)
  assert.equal(cal.max, 2)
  assert.ok(cal.months.some((mo) => mo.label === 'Nov'))
  const idx = cal.months.map((mo) => mo.index)
  assert.deepEqual(idx, [...new Set(idx)].sort((a, b) => a - b))
})

test('day labels and the table filter read the same day', () => {
  assert.match(dayLabel({ date: '2026-11-20', count: 2 }, 'en-US'), /^2 runs on Fri, Nov 20, 2026$/)
  assert.match(dayLabel({ date: '2026-11-21', count: 0 }, 'en-US'), /^No runs on /)
  assert.match(dayLabel({ date: '2026-11-22', count: 1 }, 'en-US'), /^1 run on /)
  assert.deepEqual([...namesOnDay([{ date: '2026-11-20', runs: ['a', 'b'] }], '2026-11-20')], ['a', 'b'])
  assert.equal(namesOnDay([], '2026-11-20').size, 0)
  assert.equal(dayKey(new Date(2026, 0, 5)), '2026-01-05')
})

test('intent rows are newest first, flag small samples and share one axis', () => {
  const { rows, axis, total } = intentRows([
    { run: 'old', date: '2026-10-01', rate: 10, n: 200, low: 6, high: 15 },
    { run: 'new', date: '2026-11-01', rate: 25, n: 12, low: 9, high: 53 },
    { run: 'skip', date: '2026-11-02', rate: null, n: 10 },
    { run: 'zero', date: '2026-09-01', rate: 5, n: 0 }
  ])
  assert.deepEqual(rows.map((r) => r.run), ['new', 'old'])
  assert.deepEqual(rows.map((r) => r.small), [true, false])
  assert.equal(axis, 60)
  assert.equal(total, 2)
  assert.equal(intentRows([{ run: 'a', rate: 1, n: 50 }]).axis, 10)
  assert.equal(intentRows([{ run: 'a', rate: 1, n: 50 }, { run: 'b', rate: 2, n: 50 }], 1).rows.length, 1)
  assert.equal(position(30, 60), 50)
  assert.equal(position(90, 60), 100)
  assert.equal(position(undefined, 60), 0)
})

test('numbers read plainly', () => {
  assert.equal(pct(12.345), '12.3%')
  assert.equal(pct(10), '10%')
  assert.equal(pct(null), '—')
  assert.equal(usd(1.25), '$1.25')
  assert.equal(usd(123.4), '$123')
  assert.equal(usd(undefined), '—')
  assert.deepEqual(barWidths([{ v: 10 }, { v: 5 }, { v: 0 }, { v: 0.01 }], 'v'), [100, 50, 0, 2])
  assert.deepEqual(barWidths([], 'v'), [])
})

test('trust: grade counts, words and the real-people nudge', () => {
  assert.deepEqual(gradeCounts({ D: 3, B: 1 }), [{ grade: 'A', count: 0 }, { grade: 'B', count: 1 }, { grade: 'C', count: 0 }, { grade: 'D', count: 3 }])
  assert.equal(gradeText('D'), 'sketch')
  assert.equal(gradeText(undefined), 'not graded')
  assert.match(trustNudge({ calibrated: 0 }, 4), /real people/)
  assert.equal(trustNudge({ calibrated: 1 }, 4), null)
  assert.equal(trustNudge({ calibrated: 0 }, 0), null)
  assert.equal(outcomeText('miss'), 'Missed')
  assert.equal(outcomeText('weird'), 'Waiting for real results')
})

test('live runs: only fresh ones are polled, and the stage reads plainly', () => {
  assert.deepEqual(pollable([{ name: 'a' }, { name: 'b', stale: true }, null]).map((r) => r.name), ['a'])
  assert.equal(stillRunning({ run: { runner_status: 'running' } }), true)
  assert.equal(stillRunning({ run: { runner_status: 'completed' } }), false)
  assert.equal(stillRunning({ run: { runner_status: 'running' }, finished_at: '2026-11-24T10:00:00' }), false)
  assert.equal(liveStage({ run: { current_round: 2, total_rounds: 5 } }), 'Social rounds: round 2 of 5')
  assert.equal(liveStage({ run: {}, stages: [{ label: 'Market map built', done: true }, { label: 'Simulated people created', done: false }] }),
    'Working on: simulated people created')
  assert.equal(liveStage(null, { status: 'preparing' }), 'Preparing')
  assert.equal(liveStage(null, { current_round: 1, total_rounds: 3 }), 'Social rounds: round 1 of 3')
  assert.equal(liveProgress({ run: { progress_percent: 140 } }), 100)
  assert.equal(liveProgress(null, { progress_percent: 40 }), 40)
  assert.equal(liveProgress(null, {}), null)
})
