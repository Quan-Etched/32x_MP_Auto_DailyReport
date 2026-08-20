# Where this page's contents came from

Everything on `bft-flow.html` is transcribed from the five sources below. Nothing
on that page is inferred from a number this repo collects — the L6 accessory
boards (PDB, HPB, BB) have no controller feeding OCP or pega, so unlike
`flow.html` there are no live yields here. Where a stage has no data, the box
says so.

Google's export API is read-only through the connector available here, so the
two decks could not be saved as files; their extracted text is checked in
beside this note instead (`*.txt`), with the deck IDs so the originals stay
one click away.

## 1. Pegatron overall production deck (the flow)

- Google Slides `1al4oxEe6wEzmGQEcpe42o6xr0wD6ArOXXsedeRZKiLA`
- "Overall Production in Pegatron", Eason Chuang
- Text export: `pegatron-overall-production.txt`

The flow on the page is reconstructed from three slides in it:

- **"Production Test Flowchart", updated Aug 3 2026** — the station-level chart,
  and the one `flow.html` already redraws. It is the only slide that names
  `Flash` and `BFT` as separate stages in the VBB chain.
- **"Etched | PCBA Process Flow (Sohu-VBB / -HPB / -PDB / -BB)"** — four slides,
  one per board, each ending in the stage that hands the board to assembly.
  These are what place BFT: the VBB and BB slides draw it, the HPB and PDB
  slides do not.
- **"Etched | FATP Process Flow"** and the 4U/2U/6U assembly slides — where each
  board goes once it leaves L6.

## 2. PDB/HPB/BB BFT proposal deck (the test items)

- Google Slides `1fItdEW2GPoLqvQV70FgIa8SfIOBJSmJS`
- "PDB/HPB/BB BFT Proposal" (Pega, "Pacer" series)
- Text export: `pdb-hpb-bb-bft-proposal.txt`

Source for every test-item table, the equipment lists, and the three open
questions Yibing Tang raised on 2025-12-30.

Per the 2026-08-18 XFN thread this deck is the consolidated version of three
separate Pega files, which are the ones the Jira tickets link:

- `Pacer_PDB_BFT_proposal_20260429_Gen.pptx` — Drive `18CuRdJU2haWIc-2AaFKSVHOwtPl1G6I9`
- `Pacer_HPB BFT Proposal_20260612_Gen.pptx` — Drive `1Sm7sf-n7ZUbkAgjYVjRJKESLGYzPSPHv`
- `Pacer_BB BFT proposal_20260429_Gen.pptx` — Drive `1xe5VruYCrlGGQH1mnxrLDACbEcNgoAjO`
- Fixture drawings: PDB `1w6YShI7OjV_7dcOQi3-wL2o3grZAjLfR`, BB
  `1lh511xHgoTZq-IlBnTK0uAIuJF3_uMpM` (both dated 260811); HPB still WIP at Pega

## 3. Slack — "PDB-HPB-BB-BFT XFN" (group DM `C0BR0RWSSLW`)

Opened 2026-08-18. Source for fixture status, the ~12-week lead time on all
three, and the Jira links. Members: Anu Bhari, Jun Zhang, Rohit George John,
Eason Chuang, James Lee, Ray Sanzi, Chuck Yin, Ivy Xu, Quan Shi.

## 4. Slack — `#factory-vbb-testing` (`C0BGEGBVALA`)

Source for what VBB BFT actually does today — the per-item Done/Partial status
James Lee posted 2026-08-17, the PRBS instability, the station's location, and
the fixture-count problem. VBB is the only one of the four that has run a unit,
so it is the only place the page can say what a BFT costs in practice.

## 5. Jira

- `ETCH-17772` — Pega L6 Fixture: PDB HPB BB design and support (epic, P1, In Progress)
  - `ETCH-39589` PDB BFT Readiness · `ETCH-39590` HPB BFT Readiness · `ETCH-39591` BB BFT Readiness
  - `ETCH-20787` socialize with broader team to take ownership of BB/PDB/HPB BFT fixture design (To Do)
- `ETCH-17719` — Pega L6 Fixture: VBB design and support (epic, P1, In Progress)
  - `ETCH-19981` VBB ICT Fixture (Done) · `ETCH-19982` VBB BFT Fixture (P0, In Progress)
  - `ETCH-38389` [PRBS] PRBS is not stable on the BFT station (Bug, P1, To Do, Anu Bhari)
- `ETCH-39584` — VBB BFT MP readiness (epic, P0, In Progress, James Lee)
  - `ETCH-39585` Test Stability · `ETCH-39586` Station Capacity ·
    `ETCH-39587` Test logs access · `ETCH-39588` Fixture Handling — all To Do

Read 2026-08-18. Statuses on the page are as of that date and do not refresh.
