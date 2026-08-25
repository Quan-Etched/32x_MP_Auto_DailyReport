/* The hand-kept half of the station table.
 *
 * HAND-EDITED. Nothing generates this file — edit it and commit it.
 *
 * The station table that flow.html hands out as a CSV has two kinds of column.
 * The ones that can be read from the controllers are read from them at download
 * time — the test package release actually running, and which controller holds
 * the logs — because a version number typed into a spreadsheet is out of date
 * the next time anyone deploys. The rest are facts about the line that no
 * controller knows: how many instances of a station exist, which one is the
 * canary, who the DRI is, and what the open action is. Those live here.
 *
 * Keys are the node ids in flowe2e.js. A station with no entry still appears in
 * the CSV with its computed columns filled and the rest blank, which is the
 * right default: a missing row would hide a station, a blank cell just asks
 * somebody to fill it.
 *
 * The action items below are the ones this dashboard has evidence for, with the
 * evidence named. Replace them freely — they are a first pass, not a position.
 */
(function () {
  'use strict';

  window.__FLOW_STATIONS__ = {

    /* ---------------------------------------------------------- ASIC, Sigurd */
    asic:    { location: 'Sigurd', dut: 'Die', dri: '',
               status: 'Not collected here',
               action: 'Build stage. No test data reported to this dashboard.' },
    wst:     { location: 'Sigurd', dut: 'Wafer', dri: 'Annas Javed',
               status: 'Reported weekly',
               action: 'Hand-reported in #production-test-eng; carried forward '
                     + 'on the weekly page when no new figure arrives.' },
    ft:      { location: 'Sigurd', dut: 'Die', dri: '',
               status: 'Reported weekly',
               action: 'No new figure since 2026-08-14 — the weekly page is '
                     + 'carrying it forward and marks it as carried.' },
    /* The registry has SLT on pega3 with zero runs, and the chart has it at
       Sigurd. Both cannot be right, and the CSV shows the tension rather than
       picking a side — that contradiction is one of the things this table
       exists to surface. */
    slt:     { location: 'Sigurd (registry says pega3)', dut: 'Die', dri: '',
               status: 'Skip proposed',
               action: 'Decision pending on skipping SLT — data at go/slt-ft. '
                     + 'Also: the station registry lists SLT on pega3 with no '
                     + 'runs while the flow places it at Sigurd. One of those '
                     + 'is wrong and should be settled.' },

    /* --------------------------------------------------------- PCBA L6, Pega */
    smt_bb:  { location: 'Pega', dut: 'BB board', status: '', action: '' },
    smt_hpb: { location: 'Pega', dut: 'HPB board', status: '', action: '' },
    smt_pv1: { location: 'Pega', dut: 'PV1 board', status: '', action: '' },
    smt_vbb: { location: 'Pega', dut: 'VBB board', status: '', action: '' },
    smt_pdb: { location: 'Pega', dut: 'PDB board', status: '', action: '' },

    assy_pv1: { location: 'Pega', dut: 'Module', status: '', action: '' },

    tim:     { location: 'Pega', dut: 'Module', instances: '', canary: '',
               total: '', dri: '',
               status: 'Monitored as a process',
               action: 'Now a process station: a bake failure is re-run by the '
                     + 'line, not charged to DUT yield. Confirm the floor '
                     + 'handles it that way.' },
    mlt:     { location: 'Pega', dut: 'Module', total: '3',
               instances: 'MLT-1, MLT-2, MLT-3', canary: 'MLT-4',
               dri: '', status: 'Overall stable',
               action: 'Collect error code, corrective action, screen out test '
                     + 'caused DUT failures' },
    htt:     { location: 'Pega', dut: 'Module', total: '', instances: '',
               canary: '', dri: '', status: 'Recovery at zero',
               action: '0 of 68 first-attempt failures recovered in W34 — '
                     + 'establish whether retest is being attempted at all.' },
    flash:   { location: 'Pega', dut: 'VBB board', dri: '',
               status: 'Monitored as a process',
               action: 'Reports as VBB provisioning on pega2. Process station: '
                     + 'ROT OTP, production certificate, bootloader lock.' },
    bft:     { location: 'Pega', dut: 'VBB board', dri: '',
               status: 'Not collected',
               action: 'ETCH-39584 — no controller reports BFT. Until it does, '
                     + 'the board functional test is invisible here.' },
    pdb:     { location: 'Pega', dut: 'PDB board', dri: '',
               status: 'Not collected',
               action: 'No controller reports the PDB check.' },

    /* ------------------------------------------------------- FATP L10, Pega */
    assy4u:  { location: 'Pega', dut: '4U chassis', status: '', action: '' },
    assy2u:  { location: 'Pega', dut: '2U chassis', status: '', action: '' },
    assy6u:  { location: 'Pega', dut: '6U chassis', status: '', action: '' },
    u2_comp: { location: 'Pega', dut: '2U chassis', dri: '',
               status: 'Open question',
               action: 'Shares one station key with 2U System, so the two '
                     + 'insertions cannot be told apart in the data. Which is '
                     + 'POR, and should they report separately?' },
    u2_sys:  { location: 'Pega', dut: '6U chassis', dri: '',
               status: 'Open question',
               action: 'Same station key as 2U Component. Open: one test at '
                     + 'two insertions, or two tests?' },
    fat10:   { location: 'Pega', dut: 'Server', dri: '',
               status: 'First-pass yield near zero',
               action: 'No server on rack 2 passed FAT first time — every pass '
                     + 'was a retest, at 6 to 10 attempts. Firmware and '
                     + 'provisioning dominate the failures.' },
    sft10:   { location: 'Pega', dut: 'Server', dri: '',
               status: 'Heavy retest load',
               action: '74% of graded runs are retests. CHK_DISK recurs on '
                     + 'most SFT runs.' },
    run10:   { location: 'Pega', dut: 'Server', dri: '',
               status: 'Below POR duration',
               action: 'No passing run-in has reached the 3-hour POR target. '
                     + 'Longest passes are 49 and 59 minutes.' },

    /* -------------------------------------------------------- Rack L11, Pega */
    assy11:  { location: 'Pega', dut: 'Rack', status: '', action: '' },
    prov11:  { location: 'Pega', dut: 'Rack', dri: '', status: '', action: '' },
    fat11:   { location: 'Pega', dut: 'Rack', dri: '',
               status: 'One station key for three stages',
               action: 'FAT, SFT and Runin at L11 all report under one suite, '
                     + 'so they cannot be separated in the data.' },
    sft11:   { location: 'Pega', dut: 'Rack', status: 'Counted with FAT',
               action: '' },
    run11:   { location: 'Pega', dut: 'Rack', status: 'Counted with FAT',
               action: '' },
    pack:    { location: 'Pega', dut: 'Rack', status: '', action: '' }
  };

  /* The header block at the top of the CSV. Date is filled at download time. */
  window.__FLOW_TABLE_META__ = {
    team: 'Production MTE',
    version: '0.1',
    flow: 'https://32x-production.i.etched.com/flow.html#chart=e2e'
  };
})();
