# A/B/C-mätningen: utfall

Tio funktioner i CV_Builder (fastnaglad på `361bcc0`, isolerad klon), kroppen tömd,
domartestet gömt, tre armar: **A** baslinje (Read/Grep), **B** fatta-indexet,
**C** graphify-grafen. Utfall = kör hela sviten inklusive domaren. Rådata i
`results-cvbuilder-361bcc0.json`.

## Siffrorna

| arm | gröna | tokens totalt | filer lästa |
|---|---|---|---|
| A — baslinje | 3/10 | 820 429 | 118 |
| B — fatta | 3/10 | 797 529 (−2,8 %) | 111 |
| C — graphify | 3/10 | 764 057 (−6,9 %) | 135 |

## Fynd 1: utfallet är en egenskap hos fallet, inte hos verktyget

**10 av 10 fall var samstämmiga** — alla tre armarna lyckades eller misslyckades
tillsammans, varje gång. Samma tre fall gröna, samma sju röda, ofta på exakt samma
domarfil. Verktyget påverkade inte korrektheten i ett enda fall.

Det som avgjorde var i stället om specifikationen gick att återvinna ur det synliga:
de gröna fallen bestäms helt av omgivande kod och icke-domare-tester; de röda spikar
literaler eller beteenden som **bara finns i det gömda domartestet** (exakta
felmeddelanden, exakta anropsformer, busy-guard-semantik).

## Fynd 2: tokenbesparingen är liten

−3 till −7 %, med fallvarians som är större än armskillnaderna. v1-mätningens −12 %
var till stor del en artefakt av att tester var förbjudna att läsa — när agenten får
använda tester som spec, vilket är det realistiska arbetsflödet, krymper indexens
försprång till brus­nivå. En modern agent grep:ar sig till orientering nästan lika
billigt som den slår upp den.

## Fynd 3: CF förutsade inte utfallet

Gröna: CF 352, 505, 1060. Röda: CF 283, 416, 626, 754, 1691, 3318, 10492. Röda fall
finns i hela spannet, inklusive under de gröna. Utfallet styrdes av spec-återvinnbarhet,
som är ortogonal mot förståelsefotavtrycket. CF mäter kostnaden att *läsa in sig* —
inte sannolikheten att *lyckas*, åtminstone inte i regenereringsuppgiften.

## Slutsats

I en väl­testad kodbas är flaskhalsen för en agent inte att hitta eller förstå koden —
det klarar baslinjen nästan lika billigt som båda indexen. Flaskhalsen är
**beteendespecifikation, och den bor i testerna**. Tre oberoende verktygsarmar,
identiska utfall, är ett starkt belägg.

Den praktiska produkten av det här är därför inte ett förståelseindex utan en
**testkarta**: funktion → testerna som spikar dess beteende. Graphify har redan
kanterna (tester importerar funktioner); fatta har slutningen. Kombinationen — "vill
du ändra X, läs först dessa N tester" — angriper det som faktiskt fällde 21 av 30
körningar.

## Kända svagheter

- n = 10 i en enda kodbas, en modell, en prompt per arm.
- Fall 1–2 kördes innan två läckor täpptes (fatta-indexet bar funktionskroppar;
  ab-hidden.json pekade ut domaren). Ingen agent utnyttjade dem — utfallen var röda —
  men förutsättningarna skilde sig.
- Domargömningen gör fall med domar-exklusiva literaler omöjliga per konstruktion;
  binärt pass/fail underskattar därför hur nära implementationerna kom. Testräkning
  per körning loggas från fall 4.
