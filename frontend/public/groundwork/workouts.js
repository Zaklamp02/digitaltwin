// Session definitions live in data/sessions.json; the day-by-day plan lives in the vault
// (Hobbies/Sports/Training Plan.md). Both are served by server.py.
//
// session: { id, name, tag, blocks: [block] }
// block:   { name, rounds, rest (s between exercises), roundRest (s between rounds), items: [item] }
// item:    { ex (exercise id), time (s) | holds + hold (s) | reps (waits for Done),
//            target ('~10 slow reps'), sets, sides: 'each' | 'alt', rest, weeks: [..], note }
// Any number can be a per-week list: [week1, week2, ...]; the last value repeats.

// Week numbers for per-week progressions count from this program's first Monday.
const PROGRAM = { name: 'Back & Core Program 2026', start: '2026-10-27', firstMonday: '2026-10-26', weeks: 5 };
