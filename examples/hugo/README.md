# Two real records of the Hugo family

The example family of Probandia is Victor Hugo's: every person in it died long ago, and their
records may be shown. This folder holds two of those records, with what may be done with them
(`manifest.yaml`: where each comes from, its rights, its credit line, its SHA-256).

| File | Record | Kind | Rights |
|---|---|---|---|
| `death-1885-paris-16-546.jpg` | death of Victor Marie Hugo, Paris 16th, act no. 546, 23 May 1885 | the register's page | public domain |
| `birth-1802-besancon-facsimile.jpg` | birth of Victor Marie Hugo, Besançon, act of 8 ventôse an X | a printed facsimile of the act | CC0 |

## Check a fact on the image

A finding counts only once it has been read where it is written. Open each image and check:

1. **The death.** The act is dated *le vingt trois mai* 1885, and says Victor Hugo died
   *hier au soir, à une heure et demie*: the day before, so 22 May 1885. The date of a death
   is often not the date of its act.
2. **The birth.** The act is dated *huitième du mois de ventôse l'an Dix* and says he was born
   *le jour d'hier à dix heures demie du soir*: the 7th of ventôse, year X. The engine turns the
   Republican date into a Gregorian one:

   ```bash
   probandia dates "7 ventôse an X"
   ```

   It answers `ISO=1802-02-26`.

The facsimile is a copy of the register made at the end of the 19th century: it shows the act,
but it is not the register itself, a derivative source. The death act is the register's own page.

## Use them in a project

Copy an image into `families/<family>/evidence/images/` of your project, then
`probandia transcribe new --image <file>` makes the source and the skeleton of its transcription.

Credit the records as the manifest says: "Archives de Paris, via Wikimedia Commons" and
"Maison de Victor Hugo - Hauteville House, Paris Musées".
