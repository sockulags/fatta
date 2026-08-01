# fatta

Mäter **förståelsefotavtryck** (CF) för Rust-kod: hur mycket text en läsare måste ta in för
att förstå en enskild funktion, räknat i tokens och beräknat automatiskt ur rustdoc-JSON.

## Vad CF är

Att läsa en funktion är inte att läsa dess rader. För att veta vad den gör måste man också
veta vad dess parametrar och returtyper *är* — och för att veta det måste man veta vad de
typerna i sin tur innehåller. Den kedjan är **kontraktsslutningen**.

Men man behöver inte läsa kropparna hos de funktioner den anropar. Ett kontrakt — signatur,
doc, fält, felfall — ska räcka. Det är hela abstraktionens löfte.

CF sätter en siffra på det:

```
CF(M) = tokens(M:s egen kropp)
      + Σ tokens(kontraktet) för allt M:s signatur transitivt rör vid
```

Tre val gör måttet till vad det är:

**Kontrakt, aldrig kroppar.** Beroendens implementationer räknas inte. Det är måttets
bärande antagande, och det är avsiktligt falsifierbart: om det visar sig att man i praktiken
måste läsa kropparna, då läcker abstraktionerna och måttet mäter fel sak.

**Tokens, inte rader.** Begränsningen som modelleras är ett kontextfönster, och tokens är
dess enhet.

**Välkända crates kostar noll.** `std`, `serde`, `tokio` och liknande är redan kända för
läsaren. Måttet är alltså relativt förkunskaper, vilket är en egenskap och inte en brist.
Listan står överst i `metric.py` och ska vara synlig snarare än gömd.

### Varför inte bara radantal

Sondkretsen i `probes/cfprobe` visar poängen med två funktioner:

```
funktion      LOC  kropp  slutning     CF   tyngsta beroenden
run             6     61       113    174   Config:33, Limits:29, Report:28, Stage:23
checksum       14    101         0    101
```

`run` är sex rader, men signaturen tar ett `Config` som innehåller ett `Limits` och ett
`Stage`, och returnerar ett `Report`. Allt det måste läsas. `checksum` är mer än dubbelt så
lång, men rör bara `&[u8]` och `u64` — som läsaren redan kan — så dess fotavtryck är bara
den egna kroppen.

Radantal rankar dem i motsatt ordning. Det är inversionen måttet finns för att fånga.

## Vad det ska användas till

Hypotesen är att CF förutsäger när en språkmodell misslyckas med att skriva om en modul
korrekt, och att den gör det **bättre än radantal**. Håller det går en förståelsebudget att
införa som ett kompileringsfel snarare än en stilregel.

Om CF inte tillför något utöver radantal är måttet dött. Hela försöksuppläggningen, inklusive
vad som skulle falsifiera tesen, ligger i `Code\Ideer\forstaelsebudget.md`.

## Använda

Kräver Python 3.11+, [uv](https://docs.astral.sh/uv/) och en nightly Rust-toolchain för att
generera indata.

Generera rustdoc-JSON för crate-et du vill mäta:

```bash
cargo rustdoc --lib -- -Zunstable-options --output-format json --document-private-items
```

Kör mätningen:

```bash
uv run fatta target/doc/<crate>.json
```

Nyttiga flaggor: `--no-docs` utesluter doc-kommentarer ur beroendenas kontrakt, `--csv FIL`
skriver resultatet för vidare analys, `--top N` kortar tabellen, och `--src-root DIR` behövs
när källkoden inte ligger tre nivåer ovanför JSON-filen.

## Status och öppna frågor

v0. Måttet beräknas och rangordnar, men inget är validerat mot faktiska modellmisslyckanden
än — den delen är experimentet, inte verktyget.

**Doc-kommentarer dominerar.** På `semver` v1.0.28 kommer nästan hela diskrimineringen mot
radantal från prosan i beroendenas doc-kommentarer. Med `--no-docs` faller rangordningen
tillbaka mot radantalets. Om doc räknas straffar en hård budget välkommenterade beroenden,
vilket är ett perverst incitament. Bägge varianterna måste därför tävla som prediktorer i
experimentet — frågan går inte att avgöra från fåtöljen.

**Modulen ser ut att vara rätt enhet.** Alla `matches_*`-funktioner i `semver` landar inom
några procent av varandra eftersom de delar slutning. Funktionsnivån är förmodligen för fin
för en budget.

**Tokenräkningen är en uppskattning.** `estimate_tokens` är teckenbaserad. Den duger för
rangordning men måste bytas mot en riktig tokenizer innan absoluta gränsvärden betyder något.

**Kända begränsningar i utvinningen.** Typreferenser hittas via en heuristik över
rustdoc-JSON (objekt med både `id` och `path`). Makrogenererad kod syns inte som källtext.
Generiska bounds räknas som traitens kontrakt, inte som varje möjlig impl — det är rätt
läsning, eftersom det är mot bounden anroparen programmerar, men det är ett val.
Rustdoc-formatet är instabilt; verktyget är byggt mot `FORMAT_VERSION` 61.

## Utveckla

```bash
uv run pytest
```

Testerna kör mot en incheckad fixtur och behöver ingen Rust-toolchain. Ändrar du
sondkretsen: `bash scripts/regen-fixture.sh`.
