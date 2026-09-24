"""Frontend logic tests: viz omission contract + interpretation templates.

Runs the real viz.js / interpret.js / format.js in node with minimal
stubs — no browser needed. Missing inputs must yield omission (""),
never placeholders.
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "terminal" / "js"

HARNESS = r"""
const fs = require("fs");
const path = require("path");
const root = "__ROOT__";
global.window = {};
global.document = { body: {}, createElement: () => ({}) };
function load(f) {
  const code = fs.readFileSync(path.join(root, f), "utf8");
  (0, eval)(code);
}
load("format.js"); load("viz.js"); load("interpret.js");
const V = global.window.FT_VIZ, I = global.window.FT_INTERP, F = global.window.FT_FMT;
const out = {};
out.hasV_null = V.hasV(null) === false;
out.hasV_none = V.hasV("None") === false;
out.hasV_dash = V.hasV("—") === false;
out.hasV_zero = V.hasV(0) === true;
out.hasV_str = V.hasV("hello") === true;
out.kpi_omit = V.kpiStrip([{label:"ROE",value:null},{label:"X",value:undefined}]) === "";
out.kpi_keep = V.kpiStrip([{label:"ROE",value:"42.8%"}]).includes("42.8");
out.heat_omit = V.heatmap([{label:"IT",value:null}]) === "";
out.heat_keep = V.heatmap([{label:"IT",value:-1.2}],{fmt:v=>v+"%"}).includes("IT");
out.bars_omit = V.bars([{label:"A",value:null}]) === "";
out.src_empty = V.srcLine({}) === "";
out.src_full = V.srcLine({label:"Market data",source:"yahoo",asOf:"2026-09-24T00:00:00+00:00"}).includes("2026-09-24");
out.trend_up = I.trend("Nifty 50",[100,105,110],"3M") === "Nifty 50 is up +10.00% over 3M.";
out.trend_empty = I.trend("X",[100],null) === "";
out.breadth = I.breadth(12,5,1,"the tracked universe").includes("12 up");
out.breadth_empty = I.breadth(null,5,0,"u") === "";
out.growth_cagr = I.growth("Revenue",12.4,null,"FY2023-FY2026",null) === "Revenue grew at 12.4% CAGR over FY2023-FY2026.";
out.growth_yoy = I.growth("Revenue",null,-4.2,null,"FY2026") === "Revenue declined -4.2% year on year in FY2026.";
out.growth_empty = I.growth("Revenue",null,null,null,null) === "";
out.rsi_hot = I.rsi(75).includes("overheated");
out.rsi_empty = I.rsi(null) === "";
out.vsavg = I.vsAverages(100,90,80).includes("above both");
out.regime = I.regime({trend:"bearish",momentum:"negative"}).includes("Market regime");
out.regime_empty = I.regime({}) === "";
out.sectype_idx = F.secType("^NSEI") === "INDEX";
out.sectype_stock = F.secType("TCS.NS") === "STOCK";
out.fmtstmt_cr = F.fmtStmt(2043900000,"INR") === "204.39";
out.fmtstmt_unit = F.stmtUnit("INR",2043900000) === "₹ crore";
console.log(JSON.stringify(out));
""".replace("__ROOT__", str(ROOT).replace("\\", "/"))


class FrontendLogicTest(unittest.TestCase):
    def test_viz_and_interpret(self):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(HARNESS)
            name = fh.name
        try:
            proc = subprocess.run(["node", name], capture_output=True, text=True,
                                  timeout=60, check=False)
        finally:
            Path(name).unlink(missing_ok=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[:1000])
        results = json.loads(proc.stdout.strip())
        failed = sorted(k for k, v in results.items() if v is not True)
        self.assertEqual(failed, [], msg=f"failed checks: {failed}")


if __name__ == "__main__":
    unittest.main()
