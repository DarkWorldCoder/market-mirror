# Review: MarketMirror launch film

60.6 s, 1920 x 1080, 30 fps. Built with HyperFrames from `SPEC.md`; render at `renders/marketmirror-launch.mp4`.

## Creative calls

- The story was fixed by the voiceover recorded first (ElevenLabs, voice "Justin Case", eleven_v4): hook (every launch is a bet),
  tension (the budget is gone), reveal, the people, the world, the decision, proof from the real 3,000-person run, the agent,
  end card. No alternative storylines were built.
- Three worlds from the brand's own material: the cream clay studio (hero illustration), the product's dark dashboard, and a yellow
  flood for the reveal and the payoff.
- Every product screen is the real dashboard of the 3,000-person Fitloop run, captured at 2.5x and shown at 1.15-2.2x. Yash
  Malhotra's card is rebuilt from his real record. The terminal shows the run's real command and real log lines (timestamps
  included). Nothing on screen claims a number the run did not produce.
- Transitions with a cause: colour flood (cream to dark, dark to yellow, yellow to cream), an iris from the "0" of $0, the clay
  card growing into the next world, whips between UI pieces, blur swaps on one ground, a camera punch-in and pan inside the
  decision card.

## Measured

- `hyperframes check`: 0 errors in lint, runtime, layout, motion, contrast and craft.
- Snapshots at every QA frame in `SPEC.md`, every seam and phone width were looked at; fixed: the logo covered by the clay card,
  the hero's own lettering showing, the decision card running off frame and over its title, the hook headline running into the ad.
- Audio: the mix was measured, not heard. Voice at 1.0, music at 0.38 with a 2.5 s fade-out.

## Kept on purpose

- `line_unread` warnings on the terminal log lines (they scroll as the agent runs, texture rather than reading) and on
  "A sales pitch" (the last cut of a fast four-piece montage).
- The music bed is synthesized from oscillators (no samples) because the catalog needs a HeyGen sign-in this machine does not have;
  the skill prefers a catalog track. No sound effects for the same reason. Swap `assets/audio/music.wav` for a licensed track and
  add whooshes and pops on the whips and stickers for a stronger cut.

## Weakest shot, and what I would change with more time

The survey piece in the world montage (31.6 s) is the densest: the real survey panel at 1.2x has small body text. With more time,
punch into its "1% would start the trial" card alone at 2x. Also: a 9:16 cut for Reels and Shorts, and captions for muted autoplay.
