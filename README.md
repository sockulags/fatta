# fatta

Ett **förståelseindex** över en kodbas: för varje funktion, den minsta slutna mängd man
måste förstå för att kunna ändra den — beräknad ur kompilatorns egen typinformation.

Två användningar av samma sak. Som mått: **förståelsefotavtryck** (CF), hur mycket text en
läsare måste ta in, i tokens. Som tjänst: en MCP-server som svarar en AI-agent på "vad
måste jag veta för att ändra det här", avgränsat.

Kärnan i `graph.py` är språkneutral. Frontenderna bygger samma graf: `rustdoc.py` för Rust
ur rustdoc-JSON, `tsgraph.py` plus `scripts/ts-graph.mjs` för TypeScript ur tsc:s egen
typcheckare.

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
uv run fatta scan target/doc/<crate>.json
```

Nyttiga flaggor: `--no-docs` utesluter doc-kommentarer ur beroendenas kontrakt, `--csv FIL`
skriver resultatet för vidare analys, `--top N` kortar tabellen, och `--src-root DIR` behövs
när källkoden inte ligger tre nivåer ovanför JSON-filen. För crates hämtade från crates.io
hittas källan automatiskt i registrets cache.

## TypeScript

```bash
node scripts/ts-graph.mjs ../medvind/tsconfig.json medvind.json
uv run fatta scan medvind.json --top 12
```

Emittern läser `typescript` ur projektet som analyseras, så ingen version behöver
installeras här.

## Testkartan

A/B/C-mätningen (`experiment/ab/RESULTS.md`) visade att det som avgör om en agent lyckas
ändra en funktion inte är kodförståelse utan om beteendespecifikationen går att hitta —
och den bor i testerna, ofta som enda plats i kodbasen. Testkartan gör den slagbar:

```bash
fatta testmap tsconfig.json          # bygg .fatta/testmap.json
fatta tests processImportJobById     # vilka tester spikar symbolen, och vad hävdar de?
```

Svaret listar testerna med deras expect-rader ordagrant — de exakta felmeddelanden och
anropsformer som inte går att gissa — plus vad som är mockat i testfilen. Ett tomt svar
är sin egen varning: beteendet är ospecificerat, att ändra det bryter inget test.

Tester når kod på tre sätt och kartan fångar alla: upplösta identifierare, destrukturerade
dynamiska importer (`const { GET } = await import('@/app/...')`), och källäsande tester
(`readFileSync('app/.../page.tsx')`). Hjälpfunktioner i testfilen expanderas, och
anropsgrafen bryggar indirekta träffar: testet som spikar anroparen spikar det anropade.

Validerad mot experimentets facit — de empiriskt uppmätta domarfilerna per fall: den
främsta förutsägelsen är en verklig domare i 10 av 13 fall, och 11 av 13 fall har minst
en domare i listan. Missarna är djup indirektion via komponentträd.

### Städkön: `fatta testhealth`

Äkta onåbarhet är oavgörbar, men ett test som spikar ett tillstånd produktionen aldrig
producerar måste bryta sig ur något, och brotten syns: typkast (`as any`/`as unknown`)
vid anrop av produktionskod, källäsande tester som regexar produktionsfilen, långa
literaler spikade på interna funktioner, och `@ts-expect-error`. Vattenlinjen — att
testet direktanropar en intern funktion i stället för att gå genom entrypointen — läggs
till som kontext när en annan signal slagit: den säger var det fabricerade tillståndet
uppstod, nedanför valideringen.

```bash
fatta testhealth        # rankad granskningskö med belägg per rad
```

Kö att granska, inte dom: varje signal har legitima undantag (partiella fixturer,
medveten isolering, avsiktliga brand-/copytester).

## Indexet som tjänst

```bash
uv run fatta serve medvind.json
```

En MCP-server över stdio med två verktyg. `what_must_i_know` ger den slutna mängden med
kontrakt, härkomst och kostnad. `doc_leverage` rankar var ett pålitligt kontrakt skulle
bespara mest läsning.

Skillnaden mot vanlig kodsökning är avgränsningen. En sökning ger relevant text utan
botten — du vet aldrig när du sett tillräckligt. Det här svarar "det här är allt, du kan
sluta läsa", och säger uttryckligen ifrån när det *inte* kan det: nås ett paket utan graf
sätts `bounded` till falskt och det saknade listas. Att tiga om det vore att utge mängden
för sluten när den inte är det, och då slutar agenten läsa på fel ställe.

Varje uppgift bär sin härkomst. I den här versionen är allt `derived` — härlett ur koden
och sant per konstruktion. Påstådda fakta som ingen kontrollerar finns med flit inte med:
en uppgift som får en agent att sluta läsa måste vara sann, annars är den värre än ingen
uppgift alls.

## Den blinda granskningen

Innan pengar läggs på modellkörningar behöver måttet passera en mänsklig grind: rangordnar
CF kod i en ordning som stämmer med en erfaren utvecklares magkänsla för vad som är svårt?

Ett slumpurval duger inte, för CF och radantal är överens i de flesta fall. Det som skiljer
måtten åt är paren där de rankar **tvärtom**. `fatta pairs` plockar fram dem, parar ihop dem
inom samma crate, och renderar varje par utan poäng — med slumpad men deterministisk
A/B-ordning, och kontrakten sorterade alfabetiskt i stället för på storlek, så att inget
läcker vilken funktion måttet pekar ut.

```bash
bash scripts/build-corpus.sh
uv run fatta pairs corpus/target/doc/*.json --out granskning
```

Fyll i `granskning/granskningsark.md` och utvärdera:

```bash
uv run fatta score granskning/facit.json granskning/granskningsark.md
```

Packen innehåller även kontrollpar där måtten är överens. De finns för att fånga om svaren är
slumpmässiga: ligger även kontrollerna kring hälften rätt bär inget av måtten, och då säger
oenigheterna ingenting heller.

### Mätkorpusen

Fyra crates valda för olika kodform snarare än popularitet, med versioner pinnade i
`corpus/Cargo.lock`:

- **semver** — parsning och jämförelser, välkommenterat; där doc-konfundenten slår hårdast
- **serde_json** — stora delade typer som tråcklas genom allt; där CF borde slå radantal
- **memchr** — algoritmisk kod med nästan inga egna typer; negativ kontroll
- **tokio-util** — asynkront, där svårigheten sitter i livstider och avbrottssäkerhet snarare
  än i typer. Medtaget som förutspått misslyckande: att skriva ner var måttet väntas fallera
  innan mätningen är skillnaden mellan ett test och en efterhandskonstruktion.

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

**Oenigheterna domineras av delegerande omslag.** I riktig Rust är de skarpaste fallen där CF
och radantal pekar åt olika håll nästan alltid korta funktioner som bara vidarebefordrar —
`find_iter`, `framed`, `from_value`. De rör många typer men *förstår* ingen av dem. CF som det
är definierat nu kan inte skilja "du måste begripa den här slutningen" från "du måste bara
skicka den vidare". Faller granskningen på just de paren är det förmodligen det som ska lagas,
snarare än måttet i stort: slutningen kan behöva viktas efter om funktionen rör typens inre
eller bara passerar den vidare.

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
