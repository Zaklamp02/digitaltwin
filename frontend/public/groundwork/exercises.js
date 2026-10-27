// Exercise library.
//   fig    id in figures.js (the animation)          video  looping mp4 demo (see VIDEOS at the bottom)
//   needs  equipment ids; 'a|b' means either one      subs   fallbacks, in order, when needs aren't met
//   pace   seconds per rep (sets the animation tempo) tags   back · core · arms · upper · legs · mobility

const EQUIPMENT = [
  { id: 'bench', name: 'Weight bench' },
  { id: 'barbell', name: 'Barbell + plates' },
  { id: 'ezbar', name: 'EZ bar' },
  { id: 'kettlebell', name: 'Kettlebell' },
  { id: 'dumbbells', name: 'Dumbbells' },
  { id: 'pullupbar', name: 'Pull-up bar' },
  { id: 'rope', name: 'Skipping rope' },
  { id: 'chair', name: 'Sturdy chair or sofa' },
  { id: 'table', name: 'Sturdy table (for rows underneath)' },
  { id: 'backpack', name: 'Backpack you can load' },
  { id: 'band', name: 'Resistance band' },
  { id: 'ball', name: 'Stability ball' },
  { id: 'machines', name: 'Gym machines (cable, lever, Smith)' },
];

// From the vault's Sport Equipment note (home gym), plus travel defaults.
const DEFAULT_LOCATIONS = [
  { id: 'home', name: 'Home', equipment: ['bench', 'barbell', 'ezbar', 'kettlebell', 'dumbbells', 'pullupbar', 'rope', 'chair'] },
  { id: 'travel', name: 'Travel', equipment: ['chair', 'backpack'] },
  { id: 'gym', name: 'Gym', equipment: ['bench', 'barbell', 'ezbar', 'kettlebell', 'dumbbells', 'pullupbar', 'rope', 'chair', 'band', 'ball', 'machines'] },
];

const EXERCISES = {
  // Back reset / mobility
  cat_cow: {
    name: 'Cat–cow', fig: 'cat_cow', pace: 5, tags: ['back', 'mobility'],
    cues: ['Exhale and round the back up', 'Inhale and let it sag gently', 'Slow — follow the figure'],
  },
  hip_flexor: {
    name: 'Hip flexor stretch', fig: 'hip_flexor', tags: ['back', 'mobility'],
    cues: ['Back knee down, torso tall', 'Squeeze the back glute, tuck the pelvis', 'Shift forward until the front of the hip opens'],
  },
  mcgill_curlup: {
    name: 'McGill curl-up', fig: 'mcgill_curlup', tags: ['back', 'core'],
    cues: ['One knee bent, hands under the small of your back', 'Lift head and shoulders a few cm as one block', 'Keep breathing through the hold'],
  },
  side_plank: {
    name: 'Side plank', fig: 'side_plank', tags: ['back', 'core'],
    cues: ['Elbow under shoulder', 'Straight line head to feet, hips high', 'Week 1: from the knees'],
  },
  bird_dog: {
    name: 'Bird dog', fig: 'bird_dog', tags: ['back', 'core'],
    cues: ['Flat back, hands under shoulders', 'Reach long, not high', 'Hips stay level'],
  },
  glute_bridge: {
    name: 'Glute bridge', fig: 'glute_bridge', pace: 3.5, tags: ['back', 'legs'],
    cues: ['Feet close to your bum', 'Lift with the glutes, ribs down', 'Two-second squeeze at the top'],
  },
  sl_glute_bridge: {
    name: 'Single-leg glute bridge', fig: 'sl_glute_bridge', pace: 3, tags: ['back', 'legs'],
    cues: ['Drive through the planted heel', 'Hips stay level', 'Pause at the top'],
  },
  childs_pose: {
    name: "Child's pose", fig: 'childs_pose', tags: ['back', 'mobility'],
    cues: ['Knees wide, sit back on your heels', 'Arms long, forehead down', 'Breathe into your lower back'],
  },
  dead_bug: {
    name: 'Dead bug', fig: 'dead_bug', pace: 4, tags: ['core', 'back'],
    cues: ['Lower back pressed into the floor', 'Opposite arm and leg reach out slowly', 'Exhale as you extend'],
  },
  hollow_hold: {
    name: 'Hollow hold', fig: 'hollow_hold', tags: ['core'],
    cues: ['Lower back glued down', 'Shoulders and legs just off the floor', 'Bend the knees if the back arches'],
  },
  plank: {
    name: 'Plank', fig: 'plank', tags: ['core'],
    cues: ['Elbows under shoulders', 'One long line, glutes tight', 'Breathe'],
  },
  plank_taps: {
    name: 'Plank shoulder taps', fig: 'plank_taps', pace: 2, tags: ['core', 'upper'],
    cues: ['High plank, feet wide', 'Tap the opposite shoulder', 'Hips stay still'],
  },
  prone_y_raise: {
    name: 'Prone Y raise', fig: 'prone_y_raise', pace: 3, tags: ['back', 'upper'],
    cues: ['Face down, arms overhead in a Y', 'Lift arms and chest slightly', 'Squeeze between the shoulder blades'],
  },

  // Upper body / arms
  pushup: {
    name: 'Push-up', fig: 'pushup', pace: 3, tags: ['upper', 'arms', 'core'],
    cues: ['Body in one straight line', 'Chest to a fist above the floor', 'Elbows about 45°'],
  },
  pushup_close: {
    name: 'Close-grip push-up', fig: 'pushup', pace: 3, tags: ['arms', 'upper'],
    cues: ['Hands under shoulders', 'Elbows brush your ribs', 'Slow on the way down'],
  },
  pushup_decline: {
    name: 'Decline push-up', fig: 'pushup_decline', pace: 3.5, needs: ['bench|chair'], subs: ['pushup'], tags: ['upper', 'arms', 'core'],
    cues: ['Feet up, hands on the floor', 'One straight line', 'Three seconds down'],
  },
  chinup: {
    name: 'Chin-up', fig: 'chinup', pace: 3.5, needs: ['pullupbar'], subs: ['inverted_row', 'prone_y_raise'], tags: ['upper', 'arms'],
    cues: ['Palms facing you', 'Chest to the bar', 'Lower slowly; jump up and lower if needed'],
  },
  pullup: {
    name: 'Pull-up', fig: 'pullup', pace: 3.5, needs: ['pullupbar'], subs: ['inverted_row', 'prone_y_raise'], tags: ['upper', 'arms'],
    cues: ['Palms away, a little wider than shoulders', 'Elbows down to the ribs', 'Full hang at the bottom'],
  },
  inverted_row: {
    name: 'Inverted row', fig: 'inverted_row', pace: 3, needs: ['table'], subs: ['prone_y_raise'], tags: ['upper', 'arms', 'back'],
    cues: ['Under a sturdy table, grip the edge', 'Body straight, heels down', 'Pull your chest to the edge'],
  },
  kb_row: {
    name: 'One-arm row', fig: 'kb_row', pace: 3, needs: ['kettlebell|backpack|dumbbells'], subs: ['inverted_row', 'prone_y_raise'], tags: ['upper', 'back'],
    cues: ['Hinge, back flat', 'Pull the weight to your hip', 'No twisting'],
  },
  bench_press: {
    name: 'Bench press', fig: 'bench_press', pace: 3, needs: ['barbell', 'bench'], subs: ['pushup'], tags: ['upper', 'arms'],
    cues: ['Shoulder blades pinched, feet planted', 'Lower to mid-chest', 'No spotter: a weight you can always rack'],
  },
  ez_curl: {
    name: 'EZ-bar curl', fig: 'ez_curl', pace: 3, needs: ['ezbar'], subs: ['load_curl'], tags: ['arms'],
    cues: ['Elbows pinned to your sides', 'No swinging', 'Two seconds down'],
  },
  load_curl: {
    name: 'Curl (kettlebell or backpack)', fig: 'load_curl', pace: 3, needs: ['kettlebell|backpack|dumbbells'], subs: ['chinup'], tags: ['arms'],
    cues: ['Elbow pinned to your side', 'Curl up without swinging', 'Lower slowly'],
  },
  bench_dip: {
    name: 'Bench dip', fig: 'bench_dip', pace: 3, needs: ['bench|chair'], subs: ['pushup_close'], tags: ['arms'],
    cues: ['Hands on the edge, hips close', 'Lower to about 90° at the elbow', 'Bent knees = easier'],
  },
  skullcrusher: {
    name: 'Skull crusher', fig: 'skullcrusher', pace: 3, needs: ['ezbar', 'bench'], subs: ['pushup_close'], tags: ['arms'],
    cues: ['Bar over your shoulders', 'Bend only at the elbows', 'Elbows point at the ceiling'],
  },

  // Legs / posterior chain
  hip_thrust: {
    name: 'Hip thrust', fig: 'hip_thrust', pace: 3.5, needs: ['barbell', 'bench'], subs: ['sl_glute_bridge'], tags: ['legs', 'back'],
    cues: ['Upper back on the bench, bar on the hips', 'Drive to a flat tabletop', 'Chin tucked, no arching'],
  },
  goblet_squat: {
    name: 'Goblet squat', fig: 'goblet_squat', pace: 3.5, needs: ['kettlebell|backpack|dumbbells'], subs: ['bw_squat'], tags: ['legs'],
    cues: ['Weight at your chest', 'Sit between your heels', 'Push the floor away'],
  },
  bw_squat: {
    name: 'Tempo squat', fig: 'bw_squat', pace: 4, tags: ['legs'],
    cues: ['Arms forward for balance', 'Three seconds down', 'Knees track over toes'],
  },
  rdl: {
    name: 'Romanian deadlift', fig: 'rdl', pace: 4, needs: ['kettlebell|barbell|backpack'], subs: ['sl_rdl'], tags: ['legs', 'back'],
    cues: ['Soft knees, push the hips back', 'Back stays flat', 'Stop when the hamstrings stretch'],
  },
  sl_rdl: {
    name: 'Single-leg RDL', fig: 'sl_rdl', pace: 4, tags: ['legs', 'back'],
    cues: ['Hinge on one leg', 'Back leg and torso move as one', 'Slow and balanced'],
  },
  bulgarian: {
    name: 'Bulgarian split squat', fig: 'bulgarian', pace: 3.5, needs: ['bench|chair'], subs: ['reverse_lunge'], tags: ['legs'],
    cues: ['Rear foot on the bench', 'Drop straight down', 'Front knee over the foot'],
  },
  reverse_lunge: {
    name: 'Reverse lunge', fig: 'reverse_lunge', pace: 3.5, tags: ['legs'],
    cues: ['Step back, drop the back knee', 'Torso tall', 'Drive through the front heel'],
  },
  suitcase_carry: {
    name: 'Suitcase carry', fig: 'suitcase_carry', pace: 1.4, needs: ['kettlebell|backpack|dumbbells'], subs: ['side_plank'], tags: ['core', 'back'],
    cues: ['Weight in one hand only', "Walk tall, don't lean", 'Slow steps, abs braced'],
  },
  hanging_knee_raise: {
    name: 'Hanging knee raise', fig: 'hanging_knee_raise', pace: 3.5, needs: ['pullupbar'], subs: ['dead_bug'], tags: ['core'],
    cues: ['Dead hang, shoulders engaged', 'Knees to hip height', 'No swinging'],
  },
  jump_rope: {
    name: 'Skipping', fig: 'jump_rope', pace: 0.5, needs: ['rope'], subs: ['bw_squat'], tags: ['legs'],
    cues: ['Small hops on the balls of your feet', 'Wrists turn the rope', 'Relaxed shoulders'],
  },
};

// Demo videos from the library (library/videos/<slug>.mp4) for curated exercises that have a match.
const CURATED_VIDEOS = {
  hip_flexor: 'stretching-crossover-kneeling-hip-flexor-stretch', chinup: 'close-grip-chin-up', pullup: 'pull-up-shoulder-grip',
  kb_row: 'dumbbell-bent-over-row', load_curl: 'dumbbell-biceps-curl', goblet_squat: 'dumbbell-goblet-squat',
  rdl: 'dumbbell-stiff-leg-deadlift', bw_squat: 'squat', hanging_knee_raise: 'hanging-leg-hip-raise',
  inverted_row: 'inverted-row-between-chairs', plank: 'front-plank-female', side_plank: 'side-bridge-side-plank',
  glute_bridge: 'stretching-bridge-pose-setu-bandhasana', pushup: 'push-ups', pushup_close: 'close-grip-push-ups', bench_dip: 'bench-dips',
  ez_curl: 'ez-barbell-biceps-curl', skullcrusher: 'ez-barbell-lying-triceps-extension', bench_press: 'barbell-bench-press',
  jump_rope: 'jump-rope',
};
for (const [id, slug] of Object.entries(CURATED_VIDEOS)) {
  EXERCISES[id].video = `library/videos/${slug}.mp4`;
  EXERCISES[id].poster = `library/posters/${slug}.jpg`;
}

// The full video library (library/exercises.json, 317 exercises) joins the catalogue as 'lib:<slug>'.
// Equipment and tags are derived from the dataset's own fields; curated duplicates are skipped.
const LIB_TAGS = { waist: 'core', back: 'back', 'upper arms': 'arms', 'lower arms': 'arms', 'upper legs': 'legs', 'lower legs': 'legs', hips: 'legs', shoulders: 'upper', chest: 'upper', cardio: 'cardio' };
function libNeeds(e) {
  const n = e.name.toLowerCase();
  const bench = /bench|incline|decline|lying|prone/.test(n) && !/floor/.test(n) ? ['bench'] : [];
  switch (e.equipment) {
    case 'dumbbell': return ['dumbbells', ...bench];
    case 'barbell': return ['barbell', ...bench];
    case 'ez barbell': return ['ezbar', ...bench];
    case 'kettlebell': return ['kettlebell'];
    case 'weighted': return ['dumbbells|kettlebell|backpack'];
    case 'band': return ['band'];
    case 'rope': return /jump/.test(n) ? ['rope'] : ['band'];
    case 'stability ball': return ['ball'];
    case 'cable': case 'leverage machine': case 'sled machine': case 'smith machine': return ['machines'];
    default:
      if (/chairs?\b/.test(n)) return ['chair'];
      if (/straps|parallel bars/.test(n)) return ['machines'];
      if (/pull-?up|chin-?up|hanging/.test(n)) return ['pullupbar'];
      if (/bench/.test(n)) return ['bench|chair'];
      return [];
  }
}
function loadLibrary(list) {
  const taken = new Set(Object.values(CURATED_VIDEOS));
  for (const e of list) {
    const v = (e.videos && (e.videos.male || e.videos.female)) || '';
    const t = (e.thumbnails && (e.thumbnails.male || e.thumbnails.female)) || '';
    const slug = v.split('/').pop().replace(/\.mp4$/, '');
    if (!slug || taken.has(slug)) continue;
    taken.add(slug);
    const tags = [LIB_TAGS[e.bodyPart] || 'other'];
    if (/stretch|pose|circles|rotation/i.test(e.name)) tags.push('mobility');
    EXERCISES[`lib:${slug}`] = {
      name: e.name, lib: true, needs: libNeeds(e), tags,
      video: `library/videos/${slug}.mp4`, poster: t ? `library/posters/${t.split('/').pop()}` : null,
      cues: (e.formCues || []).slice(0, 3), about: e.shortDescription || '', level: e.difficulty,
      unilateral: !!e.unilateral,
    };
  }
}
