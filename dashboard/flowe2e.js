/* End to end: the line's chart with the sub-stations the others collapse.
 *
 * WHAT THIS ONE ADDS
 * The comprehensive chart draws one box per stage. The line's own drawing has
 * more than that in three places, and each of them is a test:
 *
 *   Flash and BFT are two boxes, not one. Flash is ROT OTP, the production
 *   certificate and the bootloader lock — which is what our VBB provisioning
 *   runs are. BFT is I2C, UART, GPIO, the power-on sequence and PRBS, it is
 *   ETCH-39584, and nothing reports it to any controller yet. Drawn as one box
 *   they shared the provisioning yield, which lent a number to a test nobody
 *   is measuring.
 *   CK and PDB are checkpoints on the way into assembly.
 *   The 2U test is "2U Component" at the 2U/4U stage and "2U System" at 6U —
 *   the same station key, two different insertions, and the names say which.
 *
 * So this is the chart to read when the question is "what is actually
 * measured", because it is the one where an unmeasured stage has its own box
 * instead of hiding inside a neighbour's.
 *
 * The drawing is data; flowchart.js renders it.
 */
(function () {
  'use strict';

  var LANES = [
    { key: 'asic', title: 'ASIC',           owner: '@Sigurd',
      img: 'img/asic.png',       alt: 'Sohu ASIC package', cols: 1 },
    { key: 'l6',   title: 'PCBA L6',        owner: '@Pega',
      img: 'img/pcba.png',       alt: 'Sohu module board', cols: 3 },
    { key: 'fatp', title: 'FATP L10 2U/4U', owner: '', cols: 1 },
    { key: 'l106', title: 'FATP L10 6U',    owner: '',
      img: 'img/chassis-6u.png', alt: '6U chassis', cols: 2 },
    { key: 'l11',  title: 'Rack L11',       owner: '',
      img: 'img/rack.png',       alt: 'Rack', cols: 1 }
  ];

  var NODES = [
    { id: 'asic',   lane: 'asic', col: 1, row: 1, label: 'ASIC', kind: 'build' },
    { id: 'wst',    lane: 'asic', col: 1, row: 2, label: 'WST',  kind: 'test',
      sub: 'Wafer sort', owner: 'Sigurd' },
    { id: 'ft',     lane: 'asic', col: 1, row: 3, label: 'FT',   kind: 'test',
      sub: 'Final test', owner: 'Sigurd' },
    { id: 'slt',    lane: 'asic', col: 1, row: 4, label: 'SLT',  kind: 'test',
      sub: 'System level test', owner: 'Sigurd', station: 'slt' },

    { id: 'smt_bb',  lane: 'l6', col: 1, row: 1, label: 'BB',  kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'smt_hpb', lane: 'l6', col: 1, row: 2, label: 'HPB', kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'htt',     lane: 'l6', col: 2, row: 3, label: 'HTT', kind: 'test',
      station: 'htt' },
    /* The checkpoint between HTT and 4U assembly. On the line's chart and not
     * in any controller, so it says so. */
    { id: 'ck',      lane: 'l6', col: 3, row: 3, label: 'CK', kind: 'test',
      dashed: true, small: true, note: 'not collected' },
    { id: 'mlt',     lane: 'l6', col: 2, row: 4, label: 'MLT', kind: 'test',
      station: 'mlt' },
    { id: 'tim',     lane: 'l6', col: 2, row: 5, label: 'TIM', kind: 'test',
      sub: 'Coldplate bake', station: 'tim' },
    { id: 'smt_pv1', lane: 'l6', col: 1, row: 6, label: 'PV1', kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'assy_pv1', lane: 'l6', col: 2, row: 6, label: 'PV1 ASSY',
      kind: 'build' },
    /* Board functional test: I2C, UART, GPIO, power-on sequence, PRBS.
     * ETCH-39584. No controller reports it, so it carries no number — which is
     * the point of giving it its own box. */
    { id: 'bft',     lane: 'l6', col: 3, row: 6, label: 'BFT', kind: 'test',
      note: 'not collected · ETCH-39584' },
    { id: 'smt_vbb', lane: 'l6', col: 1, row: 7, label: 'VBB', kind: 'build',
      sub: 'SMT / ICT' },
    /* ROT OTP, production certificate, bootloader lock — the VBB provisioning
     * suites this repo does collect. */
    { id: 'flash',   lane: 'l6', col: 2, row: 7, label: 'Flash', kind: 'test',
      sub: 'OTP · cert · lock BL', station: 'vbb_provision' },
    { id: 'smt_pdb', lane: 'l6', col: 1, row: 8, label: 'PDB', kind: 'build',
      sub: 'SMT / ICT' },
    { id: 'pdb_ck',  lane: 'l6', col: 3, row: 8, label: 'PDB', kind: 'test',
      dashed: true, small: true, note: 'not collected' },

    { id: 'assy4u',  lane: 'fatp', col: 1, row: 1, label: '4U ASSY',
      kind: 'build' },
    { id: 'assy2u',  lane: 'fatp', col: 1, row: 2, label: '2U ASSY',
      kind: 'build' },
    { id: 'u2_comp', lane: 'fatp', col: 1, row: 3, label: '2U Component',
      kind: 'test', station: 'l10_2u', dashed: true, shared: true },

    { id: 'run10',   lane: 'l106', col: 2, row: 1, label: 'Runin', kind: 'test',
      station: 'l10_rin' },
    { id: 'sft10',   lane: 'l106', col: 1, row: 1, label: 'SFT',   kind: 'test',
      station: 'l10_sft' },
    { id: 'fat10',   lane: 'l106', col: 1, row: 2, label: 'FAT',   kind: 'test',
      station: 'l10_fat' },
    { id: 'u2_sys',  lane: 'l106', col: 1, row: 3, label: '2U System',
      kind: 'test', station: 'l10_2u', dashed: true, shared: true },
    { id: 'assy6u',  lane: 'l106', col: 1, row: 4, label: 'ASSY',  kind: 'build' },

    { id: 'assy11',  lane: 'l11', col: 1, row: 1, label: 'ASSY', kind: 'build' },
    { id: 'prov11',  lane: 'l11', col: 1, row: 2, label: 'Provision',
      kind: 'test', station: 'l11_provision' },
    { id: 'fat11',   lane: 'l11', col: 1, row: 3, label: 'FAT', kind: 'test',
      station: 'l11_test', shared: true },
    { id: 'sft11',   lane: 'l11', col: 1, row: 4, label: 'SFT', kind: 'test',
      station: 'l11_test', shared: true },
    { id: 'run11',   lane: 'l11', col: 1, row: 5, label: 'Runin', kind: 'test',
      station: 'l11_test', shared: true },
    { id: 'pack',    lane: 'l11', col: 1, row: 6, label: 'Pack', kind: 'pack' }
  ];

  var EDGES = [
    { from: 'asic',    to: 'wst' },
    { from: 'wst',     to: 'ft' },
    { from: 'ft',      to: 'slt',     kind: 'dashed' },
    { from: 'ft',      to: 'smt_pv1', across: true },

    { from: 'smt_pv1', to: 'assy_pv1' },
    { from: 'assy_pv1', to: 'tim' },
    { from: 'tim',     to: 'mlt' },
    { from: 'mlt',     to: 'htt' },
    { from: 'htt',     to: 'ck' },
    { from: 'ck',      to: 'assy4u',  across: true },
    { from: 'smt_hpb', to: 'assy4u',  across: true },
    { from: 'smt_bb',  to: 'assy4u',  across: true, kind: 'dashed' },

    { from: 'smt_vbb', to: 'flash' },
    { from: 'flash',   to: 'bft' },
    { from: 'bft',     to: 'assy4u',  across: true },

    { from: 'smt_pdb', to: 'pdb_ck',  kind: 'lead' },
    { from: 'pdb_ck',  to: 'assy2u',  across: true, kind: 'lead' },

    { from: 'assy2u',  to: 'u2_comp' },
    { from: 'assy4u',  to: 'assy6u',  across: true },
    { from: 'u2_comp', to: 'assy6u',  across: true },

    { from: 'assy6u',  to: 'u2_sys' },
    { from: 'u2_sys',  to: 'fat10' },
    { from: 'fat10',   to: 'sft10' },
    { from: 'sft10',   to: 'run10' },
    { from: 'run10',   to: 'assy11',  across: true },

    { from: 'assy11',  to: 'prov11' },
    { from: 'prov11',  to: 'fat11' },
    { from: 'fat11',   to: 'sft11' },
    { from: 'sft11',   to: 'run11' },
    { from: 'run11',   to: 'pack' }
  ];

  function init() {
    if (!window.FactoryFlow) return;
    window.FactoryFlow.render({
      id: 'e2e', lanes: LANES, nodes: NODES, edges: EDGES,
      /* Its own canvas: this chart shares flow.html with the summary now, and
         a shared #canvas meant whichever script ran second wiped the first.
         The page chrome is flow.js's — one page, one build stamp. */
      targets: { canvas: 'e2e-canvas', lanes: 'e2e-lanes',
                 wires: 'e2e-wires', legend: 'e2e-legend' },
      chrome: false
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
