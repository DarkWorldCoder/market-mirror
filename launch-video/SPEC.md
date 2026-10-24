# MarketMirror launch film: spec

GOAL:    the viewer understands "test your launch on simulated buyers first" and goes to the GitHub repo.
OUTPUT:  HyperFrames, 1920 x 1080, 30 fps.
TIME:    60.6 s x 30 = 1818 frames. Narrated: the voice (assets/audio/voice.mp3, 56.48 s) starts at 0.6 s and is the clock;
         every cue below is video time = voice time + 0.6. Music bed: assets/audio/music.wav, 96 BPM (18.75 frames a beat).

LOOK:    three worlds from the brand's own material, never one dark void:
         - cream clay studio (the hero illustration): ground #f4f1ea flat, ink #121211, 0% grain;
         - the product's dark mode (the dashboard): ground #0d0d0c flat, ink #f2f2ee, muted #85847c;
         - yellow flood for the reveal and the payoff: ground #f3d64b, ink #2b2005.
         Accent #f3d64b, one word or one object per frame. Red #e66767 only for money gone and the blocker.
         Display: Outfit 800, 150 px hero lines (14% of height), -3 px tracking; secondary Outfit 600 64-84 px; body Outfit 500 34 px.
         Product UI: the real dashboard pieces (assets/ui/*, captured at 2.5x from the 3,000-person run) shown at 1.25-2.2x their
         real size, flat, never tilted; radius 28 px, shadow 0 30px 80px rgba(0,0,0,.45) on dark, rgba(18,18,17,.18) on cream.
OBJECTS: a real Facebook ad from the feed test; a real brand post; the survey cards; the pitch scores; the decision card; the
         model table; one real simulated buyer (Yash Malhotra, 42, Pune) rebuilt from his record; the brand logo files; 3,000 people
         as dots; a terminal with the run's real command and log lines.

MOTION:  enter expo.out / power4.out 0.45-0.7 s; camera power2.inOut 0.5-0.6 s; exits power3.in, 40-50% of the entrance;
         springs back.out(1.4) on position and scale only; per-word blur 6 px -> 0 in 0.13 s, 0.07 s apart; titles land and hold
         still; motion blur on for fast movers.

SHOTS:   (video time)
 1  0.00-5.95  cream. "Every launch is a bet." per word on the voice (0.6-1.6), a yellow highlighter wipes under "bet" (1.75).
               The real ad card rises on the right (2.7); the question line rolls like a slot: Which ad? (2.74) -> What price? (3.61),
               a price sticker lands on the ad -> Will anyone trust it? (4.58), a real objection bubble pops. Hand-off: the ground
               floods to dark.
 2  5.95-9.95  colour flood cream -> dark (0.4 s). "$10,000 launch budget" drains to "$0" in red (7.2-9.3) under
               "Usually, you find out after the budget is gone." Hand-off: an iris opens from the 0.
 3  9.95-16.6  iris to yellow from the 0 (0.4 s). Logo wipes in on "Meet MarketMirror" (10.24). "A test market made of simulated
               buyers." per word (11.57). The clay hero card rises (13.5), "Open source. Built for AI agents." (14.05).
               Hand-off: the hero card grows past the frame into the cream world.
 4  16.6-25.85 cream. The hero blurs away into 3,000 dots counting up (16.8). "and every one is interviewed" (18.6). Yash's card
               lands (20.2); its rows land on the voice: budget 20.83, phone 21.65, asks 22.59, walks away 24.22 (in red).
               Hand-off: the card shrinks away as the ground floods dark.
 5  25.85-33.35 dark. "Your work, in front of them." (26.04). Four real pieces whip in on their words: ad 28.29, post 30.11,
               survey 31.63, pitch 32.43, each with its label. Hand-off: blur swap on the same dark ground.
 6  33.35-40.4 dark. "What happened, in plain language." (33.52). The real decision card rises (34.3). GO / ITERATE / NO-GO land on
               the voice (36.34 / 36.97 / 37.56), ITERATE fills yellow; the camera punches into the card's ITERATE (37.0), then
               pans to FIX FIRST (38.45). Hand-off: blur swap.
 7  40.4-48.75 dark. 3,000 counts up (40.57). The real model table rises (44.36). Hold 0.35 s, then a yellow flood (46.3) and
               "ITERATE." lands on the voice (46.68); "Trust was the blocker" (47.46), the bar fills to 60%.
 8  48.75-53.25 yellow -> cream flood. The agent window: the prompt types (49.0-50.3), then the real command and real log lines from
               the run land line by line (51.42-52.9). Agent names underneath (48.96).
 9  53.25-60.6 cream end card. The mark springs in, the wordmark wipes beside it (53.42), "Rehearse your launch before you spend
               on it." per word (54.52), then the repo and "Open source" (56.4), held to the end (4 s).

SOUND:   voice at 1.0; music at 0.38 under it, fading out over the last 2.5 s. No effects: no catalog access (see REVIEW.md).
BANNED:  a dark void with small floating things; glow, orbs, floating particles; tilted product UI; three cards in a row as a
         feature list; a title over a dimmed screenshot; the logo docked in a corner; every element fading and sliding up;
         titles that drift after they land; invented dashboards or numbers.
QA:      1.7 (headline landed), 4.9 (trust bubble), 9.7 ($0), 10.5 (iris), 15.5 (reveal), 19.0 (dots), 25.0 (Yash card),
         28.8 / 30.6 / 32.0 / 32.9 (each UI piece), 37.3 (iterate punch-in), 39.2 (fix first), 44.8 (table), 47.8 (payoff),
         52.8 (terminal), 58.0 (end card).
