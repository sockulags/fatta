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

```bash
cargo rustdoc -p layered -- -Zunstable-options --output-format json --document-private-items
cargo rustdoc -p uniform -- -Zunstable-options --output-format json --document-private-items
uv run fatta scan experiment/target/doc/layered.json --src-root experiment
```

Spans i ett workspace är relativa till workspace-roten, inte till paketet — därav
`--src-root experiment`.

## Utfall (2026-08-01)

Parvis per operation, alltså samma beteende jämfört mot sig självt. Kropp är funktionens
egen text, slutning är vad man måste läsa utöver den. Skiktade varianten delar flera
operationer över api- och service-nivån, så alla funktioner med samma namn summeras.

| operation | skiktad kropp | skiktad slutning | enhetlig kropp | enhetlig slutning |
|---|---|---|---|---|
| create_list | 176 | 895 | 50 | 148 |
| add | 281 | 797 | 256 | 273 |
| complete | 154 | 425 | 122 | 194 |
| reopen | 69 | 327 | 49 | 101 |
| tag | 74 | 340 | 51 | 106 |
| move_under | 268 | 542 | 192 | 154 |
| tree | 170 | 452 | 59 | 60 |
| search | 232 | 511 | 158 | 110 |
| **summa** | **1424** | **4289** | **937** | **1146** |

Kropparna skiljer 1,5 gånger. **Slutningarna skiljer 3,7 gånger.** Skillnaden sitter alltså
inte i hur mycket kod som skrivits utan i hur mycket annat man måste kunna för att läsa den.

### Rättelse (2026-08-01, senare samma dag)

Först rapporterades 9,6 gånger, och att den enhetliga slutningen var konstant över
operationerna. Bägge byggde på en modell som bara följde beroenden genom **signaturer** och
struntade i vad kroppen anropar. Den brast uppenbart i TypeScript — en React-komponent tar
inga parametrar och såg därför ut att sakna beroenden helt — men den var lika fel i Rust,
bara mindre synligt eftersom Rust-signaturer bär mer.

Med anrop inräknade står riktningen kvar men magnituden mer än halveras, och konstansen
försvinner: den var en artefakt av att modellen inte såg vad koden gjorde.

En asymmetri att känna till: TypeScript-frontenden löser upp anrop med tsc:s typcheckare,
medan Rust-frontenden matchar namn mot källtexten eftersom rustdoc-JSON saknar kroppar.
Namnmatchning överskattar, och troligen mest i den skiktade varianten som har fler distinkta
namn. Ett par tiondelar av kvoten ovan är förmodligen den effekten snarare än struktur.

## Varför siffran inte ska övertolkas

**n = 1, och samma person skrev båda.** Jag kände hypotesen medan jag skrev. Att den
skiktade varianten omedvetet blivit tyngre går inte att utesluta. Det som talar emot är att
båda klarar identiska tester, att median-LOC är 6 i båda, och att kropparna bara skiljer
1,5 gånger — hade jag bara skrivit mer kod i den ena hade den skillnaden varit större.

**CF är fortfarande en oprövad proxy.** Måttet har aldrig visats förutsäga att en modell
faktiskt misslyckas. Det här mäter slutningens storlek, inte svårighet.

**Den enhetliga varianten koncentrerar komplexiteten.** Dess tyngsta funktion, `store::load`
på 482, är värre än den skiktades värsta på 308 — men av kroppslängd, inte av slutning.

**Och det allvarligaste: CF ser inte vad man gav upp.** Den enhetliga varianten kastade
statiska garantier — `done` är strängen `"1"` — och det sänker slutningen utan att kosta
något i måttet. Optimerar man CF rakt av är den degenererade lösningen `fn do(x: &str) ->
String` överallt, med slutning noll. **CF belönar alltså precis det som gör verifiering
svårare**, och får därför aldrig bli ett optimeringsmål utan en motvikt som mäter garantier.

## Vad som redan syns utan mätning

Den enhetliga varianten betalar sitt pris i `store.rs`: med attribut som rader i stället för
kolumner slutar schemat bära mening, och kompilatorn slutar kontrollera den. `done` är
strängen `"1"`, inte en bool. Det är exakt den avvägning som förutspåddes — uniformitet köps
med statiska garantier — och den syns här i miniatyr innan något större byggts på den.
