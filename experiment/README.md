# Tvillingexperimentet

Samma todo-backend byggd två gånger, för att göra arkitekturpåståendet till en siffra:
**är en enhetlig struktur billigare att förstå än en skiktad?**

- `conformance/` — kontraktet och sviten båda måste klara. Delade typer, delade regler,
  delade tester.
- `layered/` — den konventionella företagsstacken: api över service över repository, med
  en egen typfamilj per nivå (rader, entiteter, transportobjekt) och mappare emellan.
- `uniform/` — en enda nodtyp. Listor är noder, todos är noder, deluppgifter är noder.
  Operationerna är rekursiva funktioner över noder.

Båda lagrar i SQLite och beror på exakt samma crates. Skillnaden mellan dem är strukturen
och ingenting annat — det är hela poängen med att ha en delad konformanssvit: klarar båda
den är de funktionellt utbytbara, och då är det bara formen som skiljer.

## Domänen

Tillräckligt med struktur för att skiktning ska kosta något, tillräckligt litet för att
rymmas i huvudet: listor som innehåller todos, todos som kan ha deluppgifter i godtyckligt
djup, taggar, förfallodatum, och sökning som kombinerar filter.

Den bärande regeln är rekursiv: **en todo får inte markeras klar så länge någon efterföljare
är öppen**. Den tvingar båda implementationerna att gå igenom hela subträdet, vilket är där
skillnaden mellan "samma sorts barn" och "en ny sorts sak per nivå" faktiskt märks.

## Bygga

Kräver en C-kompilator eftersom `rusqlite` bygger SQLite från källa. Den som följer med
rustups gnu-toolchain duger inte — den kan bara länka. På den här maskinen ligger en
användbar i WinLibs:

```bash
export PATH="/c/Users/lucas/AppData/Local/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.MSVCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin:$PATH"
cargo test
```

## Mäta

**Inte ännu.** CF laddar i dag för hela typdefinitioner i stället för de medlemmar koden
faktiskt rör, vilket systematiskt straffar breda strukturer. Mäts tvillingarna med det
måttet är jämförelsen riggad mot den enhetliga varianten innan den börjat.

Den användningsstyrda lagningen ska in först. Därefter:

```bash
cargo rustdoc -p layered -- -Zunstable-options --output-format json --document-private-items
cargo rustdoc -p uniform -- -Zunstable-options --output-format json --document-private-items
uv run fatta scan experiment/target/doc/layered.json
uv run fatta scan experiment/target/doc/uniform.json
```

## Vad som redan syns utan mätning

Den enhetliga varianten betalar sitt pris i `store.rs`: med attribut som rader i stället för
kolumner slutar schemat bära mening, och kompilatorn slutar kontrollera den. `done` är
strängen `"1"`, inte en bool. Det är exakt den avvägning som förutspåddes — uniformitet köps
med statiska garantier — och den syns här i miniatyr innan något större byggts på den.
