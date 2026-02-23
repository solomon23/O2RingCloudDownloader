import sys
import traceback
import webbrowser
import re

print("Script starting...", flush=True)

try:
    import os
    import glob
    import numpy as np
    from run_detector_batch import analyze_night, KNOWN_LABELS, CSV_DIR
    
    print(f"Imported run_detector_batch. CSV_DIR: {CSV_DIR}", flush=True)
except Exception as e:
    print(f"Failed to import dependencies: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)

def analyze_all():
    """Run spike detection on all CSVs and save detector_results.csv. Slow."""
    import csv as csv_mod
    print("Analyzing all CSV files...", flush=True)
    results = []

    search_path = os.path.join(CSV_DIR, "*.csv")
    csv_files = glob.glob(search_path)
    csv_files.sort(reverse=True)
    print(f"Found {len(csv_files)} files.", flush=True)

    for fpath in csv_files:
        fname = os.path.basename(fpath)
        if fname == 'detector_results.csv':
            continue
        label = KNOWN_LABELS.get(fname, fname)
        if label == fname:
            m = re.match(r'^(\d{4})(\d{2})(\d{2})\d{6}_(.*)\.csv', fname)
            if m:
                label = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}"
                label = label.replace('_', ' ')

        if not os.path.exists(fpath): continue

        try:
            chart_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data', 'charts'))
            _, res = analyze_night(fpath, label, generate_chart=True, chart_dir=chart_dir)
            if res:
                res['filename'] = fname
                results.append(res)
                print(f"  {fname} -> Score: {res.get('score', 0)}", flush=True)
            else:
                print(f"  No results for {fname}", flush=True)
        except Exception as e:
            print(f"  ERROR analyzing {fname}: {e}", flush=True)

    if not results:
        print("No results found.", flush=True)
        return []

    # Save CSV
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    csv_file = os.path.join(data_dir, 'detector_results.csv')
    keys = []
    for r in results:
        for k in r.keys():
            if k not in keys:
                keys.append(k)
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv_mod.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV saved: {csv_file} ({len(results)} sessions)", flush=True)
    return results

def load_results_from_csv():
    """Fast: load pre-computed results from detector_results.csv."""
    import csv as csv_mod
    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    csv_file = os.path.join(data_dir, 'detector_results.csv')
    if not os.path.exists(csv_file):
        return None

    results = []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv_mod.DictReader(f)
        for row in reader:
            # Convert numeric fields back from strings
            for k in row:
                if k in ('file', 'label', 'filename'):
                    continue
                try:
                    if '.' in row[k]:
                        row[k] = float(row[k])
                    else:
                        row[k] = int(row[k])
                except (ValueError, TypeError):
                    pass
            results.append(row)
    print(f"Loaded {len(results)} sessions from {csv_file}", flush=True)
    return results

def generate_report(results):
    """Generate HTML report from pre-computed results. Fast."""
    if not results:
        print("No results to generate report from.", flush=True)
        return

    html = []
    html.append("""<html>
    <head>
        <meta charset="utf-8">
        <title>HR Spike Detector Results</title>
        <style>
            body { font-family: sans-serif; margin: 10px; background-color: #fff; color: #000; }
            table { border-collapse: collapse; width: 100%; font-size: 13px; }
            th, td { border: 1px solid #ddd; padding: 4px 6px; text-align: center; }
            th { background-color: #f2f2f2; position: sticky; top: 0; cursor: pointer; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            tr:hover { background-color: #f1f1f1; }
            .left-align { text-align: left; }
            .mono { font-family: monospace; }
            .disabled-row { opacity: 0.3; }
            .selected-row { background-color: #dbeafe !important; box-shadow: inset 0 0 0 2px #3b82f6; }
            .editable-label { cursor: text; border-bottom: 1px dashed #ccc; min-width: 100px; display: inline-block; padding: 2px; }
            .editable-label:focus { outline: 1px solid #00f; background-color: #fff; }
        </style>
        <script src="https://www.kryogenix.org/code/browser/sorttable/sorttable.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns"></script>
        <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation"></script>
        <script>
            function openChart(url) {
                document.getElementById('chartIframe').src = url;
                document.getElementById('chartModal').style.display = 'flex';
            }
            
            const metricsFields = ['score', 'si', 'tab', 'delta', 'p90', 'pc10', 'pc15', 'events_A_ph', 'events_B_ph', 'events_C_ph'];
            
            function getColor(value, min_val, max_val, inverse) {
                if (isNaN(value)) return "#ffffff";
                if (min_val === max_val) return "#ffffff";
                let range = max_val - min_val;
                let norm = (value - min_val) / range;
                norm = Math.max(0.0, Math.min(1.0, norm));
                if (inverse) norm = 1.0 - norm;
                
                let r, g, b;
                if (norm < 0.5) {
                    r = Math.floor(norm * 2 * 255);
                    g = 255;
                    b = 0;
                } else {
                    r = 255;
                    g = Math.floor((1.0 - norm) * 2 * 255);
                    b = 0;
                }
                
                let hex = (r << 16 | g << 8 | b).toString(16).padStart(6, '0');
                return "#" + hex;
            }

            function updateColors() {
                let rows = document.querySelectorAll("tbody tr");
                let mins = {};
                let maxs = {};
                
                metricsFields.forEach(m => {
                    mins[m] = Infinity;
                    maxs[m] = -Infinity;
                });
                
                // First pass: find min/max ONLY for enabled rows
                rows.forEach(row => {
                    let cb = row.querySelector('.row-checkbox');
                    if (cb && cb.checked) {
                        metricsFields.forEach(m => {
                            let cell = row.querySelector(`.cell-${m}`);
                            if (cell) {
                                let val = parseFloat(cell.dataset.value);
                                if (!isNaN(val)) {
                                    if (val < mins[m]) mins[m] = val;
                                    if (val > maxs[m]) maxs[m] = val;
                                }
                            }
                        });
                    }
                });
                
                // Second pass: apply colors to ALL rows using the min/max from enabled rows
                rows.forEach(row => {
                    let cb = row.querySelector('.row-checkbox');
                    let isChecked = cb && cb.checked;
                    
                    if (isChecked) {
                        row.classList.remove('disabled-row');
                    } else {
                        row.classList.add('disabled-row');
                    }
                    
                    metricsFields.forEach(m => {
                        let cell = row.querySelector(`.cell-${m}`);
                        if (cell) {
                            let val = parseFloat(cell.dataset.value);
                            // It will colorize based on the checked-rows scale. 
                            // If a value is outside the checked min/max, it clamps to min/max colors.
                            let bg = getColor(val, mins[m], maxs[m], false);
                            cell.style.backgroundColor = bg;
                            // Use white text on dark backgrounds for readability
                            let [cr, cg, cb] = [parseInt(bg.slice(1,3),16), parseInt(bg.slice(3,5),16), parseInt(bg.slice(5,7),16)];
                            let luminance = (0.299*cr + 0.587*cg + 0.114*cb);
                            cell.style.color = luminance < 140 ? '#ffffff' : '#000000';
                        }
                    });
                });
            }
            
            function saveData() {
                let rows = document.querySelectorAll("tbody tr");
                let data = {};
                let merges = [];
                rows.forEach(row => {
                    let filename = row.dataset.filename;
                    
                    if (row.dataset.isMerged === "true") {
                        if (row.style.display !== 'none') {
                            merges.push(filename.split(' + '));
                        }
                    }

                    let cb = row.querySelector('.row-checkbox');
                    let labelNode = row.querySelector('.editable-label');
                    if (filename && cb && labelNode) {
                        let entry = { checked: cb.checked };
                        if (labelNode.dataset.edited === "true") {
                            entry.label = labelNode.innerText;
                        }
                        data[filename] = entry;
                    }
                });
                localStorage.setItem('hrSpikeDataV2', JSON.stringify(data));
                localStorage.setItem('hrSpikeMergesV2', JSON.stringify(merges));
            }
            
            function loadData() {
                let savedMerges = localStorage.getItem('hrSpikeMergesV2');
                if (savedMerges) {
                    try {
                        let merges = JSON.parse(savedMerges);
                        merges.forEach(mergeObj => {
                            let rowsToMerge = [];
                            let allRows = Array.from(document.querySelectorAll("tbody tr"));
                            mergeObj.forEach(fname => {
                                let row = allRows.find(r => r.dataset.filename === fname);
                                if (row && row.style.display !== 'none') {
                                    rowsToMerge.push(row);
                                }
                            });
                            if (rowsToMerge.length === mergeObj.length) {
                                doMergeForRows(rowsToMerge, false);
                            }
                        });
                    } catch(e) {}
                }

                let saved = localStorage.getItem('hrSpikeDataV2');
                if (saved) {
                    try {
                        let data = JSON.parse(saved);
                        let rows = document.querySelectorAll("tbody tr");
                        rows.forEach(row => {
                            let filename = row.dataset.filename;
                            if (filename && data[filename]) {
                                let cb = row.querySelector('.row-checkbox');
                                let labelNode = row.querySelector('.editable-label');
                                if (data[filename].checked !== undefined) {
                                    cb.checked = data[filename].checked;
                                }
                                if (data[filename].label) {
                                    labelNode.innerText = data[filename].label;
                                    labelNode.dataset.edited = "true";
                                }
                            }
                        });
                    } catch(e) {}
                }
            }

            function mergeSelected() {
                let rows = Array.from(document.querySelectorAll("tbody tr")).filter(row => {
                    return row.classList.contains('selected-row') && row.style.display !== 'none';
                });

                if (rows.length < 2) {
                    alert("Please select at least 2 rows to merge using Ctrl+Click (or Cmd+Click).");
                    return;
                }

                doMergeForRows(rows, true);
            }

            function doMergeForRows(rows, saveAfter) {
                if (rows.length < 2) return;
                
                let totalHrs = 0, totalEvents = 0, totalEvents10 = 0, totalEvents15 = 0;
                let totalMajorA = 0, totalMajorB = 0, totalMajorC = 0;
                let sumTab = 0, sumScore = 0, sumDelta = 0, sumP90 = 0;
                let sumTypeA = 0, sumTypeB = 0, sumTypeC = 0;
                let filenames = [], labels = [];

                rows.forEach(row => {
                    let hrs = parseFloat(row.cells[3].dataset.sort) || 0;
                    totalHrs += hrs;

                    let evts = parseFloat(row.cells[12].innerText) || 0;
                    totalEvents += evts;

                    let pcArr = row.cells[13].innerText.split('/');
                    totalEvents10 += parseInt(pcArr[0] || 0);
                    totalEvents15 += parseInt(pcArr[1] || 0);

                    totalMajorA += parseInt(row.cells[17].innerText) || 0;
                    totalMajorB += parseInt(row.cells[18].innerText) || 0;
                    totalMajorC += parseInt(row.cells[19].innerText) || 0;

                    sumTab += (parseFloat(row.querySelector('.cell-tab').dataset.value) || 0) * hrs;
                    sumScore += (parseFloat(row.querySelector('.cell-score').dataset.value) || 0) * hrs;

                    sumDelta += (parseFloat(row.querySelector('.cell-delta').dataset.value) || 0) * evts;
                    sumP90 += (parseFloat(row.querySelector('.cell-p90').dataset.value) || 0) * evts;

                    let typeArr = row.cells[11].innerText.split('/');
                    sumTypeA += (parseFloat(typeArr[0]) || 0) * evts;
                    sumTypeB += (parseFloat(typeArr[1]) || 0) * evts;
                    sumTypeC += (parseFloat(typeArr[2]) || 0) * evts;

                    filenames.push(row.cells[20].innerText);
                    labels.push(row.querySelector('.editable-label').innerText);

                    // Unselect and hide
                    row.classList.remove('selected-row');
                    row.style.display = 'none';
                });

                if (totalHrs === 0) return;

                let newTab = sumTab / totalHrs;
                let newScore = sumScore / totalHrs;
                let newDelta = totalEvents > 0 ? sumDelta / totalEvents : 0;
                let newP90 = totalEvents > 0 ? sumP90 / totalEvents : 0;
                
                let newSi = totalEvents / totalHrs;
                let newPc10ph = totalEvents10 / totalHrs;
                let newPc15ph = totalEvents15 / totalHrs;
                
                let newTypeA = totalEvents > 0 ? sumTypeA / totalEvents : 0;
                let newTypeB = totalEvents > 0 ? sumTypeB / totalEvents : 0;
                let newTypeC = totalEvents > 0 ? sumTypeC / totalEvents : 0;
                
                let newMajorAph = totalMajorA / totalHrs;
                let newMajorBph = totalMajorB / totalHrs;
                let newMajorCph = totalMajorC / totalHrs;

                let h = Math.floor(totalHrs);
                let m = Math.round((totalHrs - h) * 60);
                if (m === 60) { h++; m=0; }
                let hrStr = `${h}h ${m.toString().padStart(2, '0')}m`;

                let firstRow = rows[0];
                let mergedDate = firstRow ? firstRow.cells[1].innerHTML : "Merged Date";

                let tr = document.createElement('tr');
                tr.dataset.filename = filenames.join(' + ');
                tr.dataset.isMerged = "true";

                tr.innerHTML = `
                    <td><input type="checkbox" class="row-checkbox" checked></td>
                    <td class="left-align" style="white-space: nowrap;">${mergedDate}</td>
                    <td class="left-align" style="font-size:11px;"><span class="editable-label" contenteditable="true">Merged: ${labels.join(' + ')}</span></td>
                    <td data-sort="${totalHrs}">${hrStr}</td>
                    <td class="cell-score" data-value="${newScore.toFixed(1)}">${newScore.toFixed(1)}</td>
                    <td class="cell-tab" data-value="${newTab.toFixed(1)}">${newTab.toFixed(1)}</td>
                    <td class="cell-delta" data-value="${newDelta.toFixed(1)}">${newDelta.toFixed(1)}</td>
                    <td class="cell-p90" data-value="${newP90.toFixed(1)}">${newP90.toFixed(1)}</td>
                    <td class="cell-si" data-value="${newSi.toFixed(1)}">${newSi.toFixed(1)}</td>
                    <td class="cell-pc10" data-value="${newPc10ph.toFixed(1)}">${newPc10ph.toFixed(1)}</td>
                    <td class="cell-pc15" data-value="${newPc15ph.toFixed(1)}">${newPc15ph.toFixed(1)}</td>
                    <td>${Math.round(newTypeA)}/${Math.round(newTypeB)}/${Math.round(newTypeC)}</td>
                    <td>${totalEvents}</td>
                    <td>${totalEvents10}/${totalEvents15}</td>
                    <td class="cell-events_A_ph" data-value="${newMajorAph.toFixed(1)}">${newMajorAph.toFixed(1)}</td>
                    <td class="cell-events_B_ph" data-value="${newMajorBph.toFixed(1)}">${newMajorBph.toFixed(1)}</td>
                    <td class="cell-events_C_ph" data-value="${newMajorCph.toFixed(1)}">${newMajorCph.toFixed(1)}</td>
                    <td>${totalMajorA}</td>
                    <td>${totalMajorB}</td>
                    <td>${totalMajorC}</td>
                    <td class="left-align mono" style="font-size:11px;" title="${filenames.join('\\n')}">
                        Merged (${filenames.length} sessions)
                        <button class="unmerge-btn" style="margin-left: 5px; padding: 2px 4px; font-size: 9px; cursor: pointer;">Unmerge</button>
                    </td>
                `;

                if (firstRow && firstRow.parentNode) {
                    firstRow.parentNode.insertBefore(tr, firstRow);
                } else {
                    let tbody = document.querySelector('tbody');
                    tbody.insertBefore(tr, tbody.firstChild);
                }

                tr.querySelector('.row-checkbox').addEventListener('change', () => { updateColors(); updateChart(); saveData(); });
                tr.querySelector('.editable-label').addEventListener('input', () => { tr.querySelector('.editable-label').dataset.edited = "true"; saveData(); });
                
                tr.querySelector('.unmerge-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (confirm("Are you sure you want to unmerge these sessions?")) {
                        tr.remove();
                        rows.forEach(r => {
                            r.style.display = '';
                        });
                        updateColors();
                        saveData();
                        updateMergeButtonState();
                    }
                });

                tr.addEventListener('click', (e) => {
                    if (e.target.tagName.toLowerCase() === 'button' || e.target.tagName.toLowerCase() === 'input') return;
                    if (e.ctrlKey || e.metaKey) {
                        e.stopPropagation();
                        tr.classList.toggle('selected-row');
                        updateMergeButtonState();
                    }
                });

                if (saveAfter) {
                    updateColors();
                    saveData();
                    updateMergeButtonState();
                }
            }
            
            function updateMergeButtonState() {
                let selectedCount = document.querySelectorAll("tbody tr.selected-row").length;
                let btn = document.getElementById('mergeBtn');
                if (btn) {
                    btn.disabled = selectedCount < 2;
                    if (btn.disabled) {
                        btn.style.opacity = '0.5';
                        btn.style.cursor = 'not-allowed';
                    } else {
                        btn.style.opacity = '1';
                        btn.style.cursor = 'pointer';
                    }
                }
            }

            let scoreChart = null;
            function updateChart() {
                let rows = Array.from(document.querySelectorAll("tbody tr"));
                let entries = [];
                rows.forEach(row => {
                    if (row.style.display === 'none') return;
                    let cb = row.querySelector('.row-checkbox');
                    if (!cb || !cb.checked) return;
                    let ts = parseFloat(row.dataset.timestamp);
                    let scoreCell = row.querySelector('.cell-score');
                    if (!ts || !scoreCell) return;
                    let score = parseFloat(scoreCell.dataset.value);
                    if (isNaN(score)) return;
                    let d = new Date(ts * 1000);
                    let label = (d.getMonth()+1) + '/' + d.getDate() + '/' + String(d.getFullYear()).slice(2);
                    entries.push({ date: d, label: label, score: score });
                });
                entries.sort((a, b) => a.date - b.date);

                let labels = entries.map(e => e.label);
                let scores = entries.map(e => e.score);

                // Compute y-axis range from data
                let minScore = Infinity, maxScore = -Infinity;
                scores.forEach(s => {
                    if (s < minScore) minScore = s;
                    if (s > maxScore) maxScore = s;
                });
                // Include nearest severity thresholds in range
                let severityLines = [15, 30, 50, 75];
                let nearestBelow = 0;
                let nearestAbove = 100;
                severityLines.forEach(s => {
                    if (s <= minScore) nearestBelow = Math.max(nearestBelow, s);
                    if (s >= maxScore) nearestAbove = Math.min(nearestAbove, s);
                });
                let yMin = Math.max(0, nearestBelow - 3);
                let yMax = Math.min(100, nearestAbove + 3);

                // Compute running average (window of 5)
                let window = Math.min(5, Math.floor(scores.length / 2)) || 1;
                let trend = scores.map((_, i) => {
                    let start = Math.max(0, i - Math.floor(window / 2));
                    let end = Math.min(scores.length, start + window);
                    if (end === scores.length) start = Math.max(0, end - window);
                    let sum = 0;
                    for (let j = start; j < end; j++) sum += scores[j];
                    return +(sum / (end - start)).toFixed(1);
                });

                let ctx = document.getElementById('scoreChart').getContext('2d');
                if (scoreChart) {
                    scoreChart.data.labels = labels;
                    scoreChart.data.datasets[0].data = scores;
                    scoreChart.data.datasets[1].data = trend;
                    scoreChart.options.scales.y.min = yMin;
                    scoreChart.options.scales.y.max = yMax;
                    scoreChart.update();
                } else {
                    scoreChart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: labels,
                            datasets: [{
                                label: 'Score',
                                data: scores,
                                borderColor: '#e53e3e',
                                backgroundColor: 'rgba(229, 62, 62, 0.1)',
                                fill: true,
                                tension: 0.3,
                                pointRadius: 4,
                                pointHoverRadius: 7
                            },
                            {
                                label: 'Trend',
                                data: trend,
                                borderColor: '#3182ce',
                                borderWidth: 2,
                                borderDash: [6, 4],
                                pointRadius: 0,
                                fill: false,
                                tension: 0
                            }]
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            scales: {
                                x: {
                                    title: { display: true, text: 'Date' },
                                    ticks: {
                                        autoSkip: true,
                                        maxTicksToShow: 25,
                                        maxRotation: 45
                                    }
                                },
                                y: {
                                    title: { display: true, text: 'Score (0-100)' },
                                    min: yMin,
                                    max: yMax
                                }
                            },
                            plugins: {
                                tooltip: {
                                    callbacks: {
                                        label: function(ctx) {
                                            return 'Score: ' + ctx.parsed.y.toFixed(1);
                                        }
                                    }
                                },
                                annotation: {
                                    annotations: {
                                        normal: {
                                            type: 'line', yMin: 15, yMax: 15,
                                            borderColor: 'rgba(34,197,94,0.5)', borderWidth: 1, borderDash: [4,4],
                                            label: { display: true, content: 'Mild > 15', position: 'start', font: {size: 10}, color: 'rgba(34,197,94,0.8)', backgroundColor: 'rgba(255,255,255,0.8)' }
                                        },
                                        mild: {
                                            type: 'line', yMin: 30, yMax: 30,
                                            borderColor: 'rgba(234,179,8,0.5)', borderWidth: 1, borderDash: [4,4],
                                            label: { display: true, content: 'Moderate > 30', position: 'start', font: {size: 10}, color: 'rgba(161,125,0,0.8)', backgroundColor: 'rgba(255,255,255,0.8)' }
                                        },
                                        moderate: {
                                            type: 'line', yMin: 50, yMax: 50,
                                            borderColor: 'rgba(249,115,22,0.5)', borderWidth: 1, borderDash: [4,4],
                                            label: { display: true, content: 'Severe > 50', position: 'start', font: {size: 10}, color: 'rgba(194,80,10,0.8)', backgroundColor: 'rgba(255,255,255,0.8)' }
                                        },
                                        severe: {
                                            type: 'line', yMin: 75, yMax: 75,
                                            borderColor: 'rgba(239,68,68,0.5)', borderWidth: 1, borderDash: [4,4],
                                            label: { display: true, content: 'Very Severe > 75', position: 'start', font: {size: 10}, color: 'rgba(185,50,50,0.8)', backgroundColor: 'rgba(255,255,255,0.8)' }
                                        }
                                    }
                                }
                            }
                        }
                    });
                }
            }

            document.addEventListener("DOMContentLoaded", () => {
                loadData();
                updateColors();
                updateChart();
                updateMergeButtonState();
                
                // Attach event listeners to rows for Ctrl+Click selection
                document.querySelectorAll('tbody tr').forEach(row => {
                    row.addEventListener('click', (e) => {
                        // Ignore clicks on checkboxes and editable labels
                        if (e.target.tagName.toLowerCase() === 'input' || e.target.classList.contains('editable-label')) {
                            return;
                        }
                        if (e.ctrlKey || e.metaKey) {
                            // Prevent text selection when ctrl clicking
                            e.preventDefault();
                            row.classList.toggle('selected-row');
                            updateMergeButtonState();
                        }
                    });
                });
                
                // Attach event listeners to checkboxes
                document.querySelectorAll('.row-checkbox').forEach(cb => {
                    cb.addEventListener('change', () => {
                        updateColors();
                        updateChart();
                        saveData();
                    });
                });
                
                // Attach event listeners to labels
                document.querySelectorAll('.editable-label').forEach(lbl => {
                    lbl.addEventListener('input', () => {
                        lbl.dataset.edited = "true";
                        saveData();
                    });
                });
            });
        </script>
    </head>
    <body>
        <div id="chartModal" style="display:none; position:fixed; top:5%; left:2%; width:96%; height:90%; background:white; z-index:1000; border:2px solid #ccc; box-shadow:0 0 20px rgba(0,0,0,0.5); flex-direction: column;">
            <div style="background:#f8f9fa; padding:10px;text-align:right; border-bottom:1px solid #ddd; flex-shrink: 0;">
                <button onclick="document.getElementById('chartModal').style.display='none';" style="padding:6px 15px; cursor:pointer; font-weight:bold; border-radius:4px; border:1px solid #ccc; background:#fff;">Close Chart</button>
            </div>
            <iframe id="chartIframe" style="width:100%; flex-grow: 1; border:none;"></iframe>
        </div>
        <h1>HR Spike Detection Results</h1>
        <p>
            Generated report. Columns with colors indicate severity (Green=Low, Red=High). Uncheck rows to exclude from color scaling. Edit labels directly.<br><br>
            <button id="mergeBtn" onclick="mergeSelected()" disabled style="padding: 6px 12px; font-weight: bold; cursor: not-allowed; opacity: 0.5; background-color: #2196F3; color: white; border: none; border-radius: 4px;">Merge Selected Rows (UI Only)</button>
            <span style="font-size: 11px; margin-left: 10px;"><b>Ctrl+Click</b> (or Cmd+Click on Mac) the rows you want to merge to select them. Merged states are loaded automatically.</span><br><br>
            <strong>Event Threshold:</strong> A spike is counted if HR rises &ge;6 bpm (or +8% from baseline), is sustained for &ge;2s with a rise rate of &ge;0.8 bpm/sec.<br>
            <strong>Scientific Basis:</strong> This threshold matches the <strong>PRRI-6</strong> (pulse rate rises &gt;6 bpm) metric validated as a screening marker for sleep fragmentation. 
            Source: <a href="https://pubmed.ncbi.nlm.nih.gov/14607348/" target="_blank">Adachi et al., "Clinical significance of pulse rate rise during sleep..." (Sleep Medicine, 2003)</a>. 
            DOI: <a href="https://doi.org/10.1016/j.sleep.2003.06.003" target="_blank">10.1016/j.sleep.2003.06.003</a>.<br>
            <strong>Metrics Breakdown:</strong>
            <ul>
                <li><strong>Score (0-100):</strong> A weighted composite score of Frequency (SI/h), Magnitude (TAB), Intensity (P90), and Pattern characteristics.</li>
                <li><strong>Spike (PC) Total index/hr:</strong> Total events divided by total valid sleep hours. Indicates how often the nervous system is reacting.</li>
                <li><strong>TAB:</strong> Total Autonomic Burden. The sum of the area-under-the-curve for all spikes, heavily reflecting spike duration and intensity.</li>
                <li><strong>Mean ΔHR:</strong> The average heart rate jump (in bpm) across all spikes.</li>
                <li><strong>Intensity (P90Δ):</strong> The 90th percentile peak jump. Shows the intensity of the worst 10% of your spikes.</li>
                <li><strong>Type A/B/C %:</strong> Characteristics of the spikes (A=Drop/Recovery, B=Sustained/No Recovery, C=Blunted).</li>
            </ul>
        </p>
        <div style="height: 300px; margin-bottom: 20px;">
            <canvas id="scoreChart"></canvas>
        </div>
        <table class="sortable">
            <thead>
                <tr>
                    <th class="sorttable_nosort">Inc</th>
                    <th class="left-align" style="white-space: nowrap;">Date / Time</th>
                    <th class="left-align">Notes</th>
                    <th>Length</th>
                    <th>Score (0-100)</th>
                    <th>TAB</th>
                    <th>Mean ΔHR</th>
                    <th>Intensity (P90Δ)</th>
                    <th>Spike (PC) Total index/hr</th>
                    <th>PC10/hr</th>
                    <th>PC15/hr</th>
                    <th>Type A/B/C %</th>
                    <th>Events</th>
                    <th>Events &ge;10/15</th>
                    <th title="Major Spike Detector: 15bpm min delta, 120s refractor (Per Hour)">Major A / hr</th>
                    <th title="Major Spike Detector: 20bpm min delta, 60s refractor (Per Hour)">Major B / hr</th>
                    <th title="Major Spike Detector: 18bpm min delta, 60s refractor (Per Hour)">Major C / hr</th>
                    <th title="Major Spike Detector: 15bpm min delta, 120s refractor (Total Count)">Major A (Total)</th>
                    <th title="Major Spike Detector: 20bpm min delta, 60s refractor (Total Count)">Major B (Total)</th>
                    <th title="Major Spike Detector: 18bpm min delta, 60s refractor (Total Count)">Major C (Total)</th>
                    <th class="left-align">Filename</th>
                </tr>
            </thead>
            <tbody>""")

    import datetime

    for r in results:
        def cell(metric_key, val):
            return f'<td class="cell-{metric_key}" data-value="{val}">{val}</td>'
        
        # Calculate formatted hours
        hrs_exact = r.get('hours_exact', r['hours'])
        h = int(hrs_exact)
        m = int(round((hrs_exact - h) * 60))
        if m == 60:
            h += 1
            m = 0
        hr_str = f"{h}h {m:02d}m"
        
        # Calculate split absolute events
        events_10 = int(round(r['pc10_per_hr'] * hrs_exact))
        events_15 = int(round(r['pc15_per_hr'] * hrs_exact))
        pc_split = f"{events_10}/{events_15}"
        
        # Extract date string from filename using datetime
        fname = r['filename']
        date_str = ""
        timestamp_epoch = 0
        m_date = re.match(r'^(\d{14})_', fname)
        if m_date:
            try:
                dt = datetime.datetime.strptime(m_date.group(1), "%Y%m%d%H%M%S")
                timestamp_epoch = dt.timestamp()
                prev_dt = dt - datetime.timedelta(days=1)
                time_str = dt.strftime("%I:%M%p").lstrip("0").lower()
                date_str = f"{prev_dt.month}/{prev_dt.day}-{dt.month}/{dt.day}/{dt.strftime('%y')} {time_str}"
            except:
                pass

        if not date_str:
            # fallback
            m_date = re.match(r'^(\d{4})(\d{2})(\d{2})\d{6}_(.*)\.csv', fname)
            if m_date:
                date_str = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}"
                time_part = m_date.group(4).split('_')[0] if '_' in m_date.group(4) else m_date.group(4)
                date_str += f" ({time_part})"

        type_str = f"{r.get('pct_a', 0):.0f}/{r.get('pct_b', 0):.0f}/{r.get('pct_c', 0):.0f}"

        # Uncheck daytime sessions by default (start hour before 8pm / after 6am)
        is_daytime = False
        m_hour = re.match(r'^\d{8}(\d{2})', fname)
        if m_hour:
            hour = int(m_hour.group(1))
            if 6 <= hour < 20:
                is_daytime = True
        checked_attr = "" if is_daytime else "checked"

        html.append(f"<tr data-filename='{fname}' data-timestamp='{timestamp_epoch}'>")
        html.append(f'<td><input type="checkbox" class="row-checkbox" {checked_attr}></td>')
        chart_fname = fname.replace('.csv', '_chart.html')
        html.append(f'<td class="left-align" style="white-space: nowrap;"><a href="javascript:openChart(\'charts/{chart_fname}\');" style="text-decoration:none; color:#0366d6;">{date_str}</a></td>')
        # Split label into display label and notes
        label_text = r["label"]
        # Strip date prefix and time/duration suffix, whatever remains is notes
        tmp = label_text
        tmp = re.sub(r'^\d{4}-\d{2}-\d{2}\s*', '', tmp)
        tmp = re.sub(r'^\d+/\d+-\d+/\d+\s*', '', tmp)
        tmp = re.sub(r'\d+[ap]m\s+\d+h\s+\d+m\s*$', '', tmp)
        notes_text = tmp.strip()
        html.append(f'<td class="left-align" style="font-size:11px; max-width:250px;"><span class="editable-label" contenteditable="true">{notes_text}</span></td>')
        html.append(f'<td data-sort="{hrs_exact}">{hr_str}</td>')
        html.append(cell('score', r['score']))
        html.append(cell('tab', r['tab']))
        html.append(cell('delta', r['mean_delta']))
        html.append(cell('p90', r.get('p90_delta', 0)))
        html.append(cell('si', r['si']))
        html.append(cell('pc10', r['pc10_per_hr']))
        html.append(cell('pc15', r['pc15_per_hr']))
        html.append(f'<td>{type_str}</td>')
        html.append(f'<td>{r["events"]}</td>')
        html.append(f'<td>{pc_split}</td>')
        html.append(cell('events_A_ph', r.get('events_A_ph', 0)))
        html.append(cell('events_B_ph', r.get('events_B_ph', 0)))
        html.append(cell('events_C_ph', r.get('events_C_ph', 0)))
        html.append(f'<td>{r.get("events_A", 0)}</td>')
        html.append(f'<td>{r.get("events_B", 0)}</td>')
        html.append(f'<td>{r.get("events_C", 0)}</td>')
        html.append(f'<td class="left-align mono" style="font-size:11px;">{fname}</td>')
        html.append("</tr>")

    html.append("""</tbody></table></body></html>""")

    data_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    out_file = os.path.join(data_dir, 'detector_results.html')
    try:
        with open(out_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(html))
        print(f"HTML Report generated: {out_file}", flush=True)
    except Exception as e:
        print(f"Failed to write HTML report: {e}", flush=True)
        traceback.print_exc()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--analyze', action='store_true',
                        help='Re-analyze all CSVs (slow). Without this, uses cached detector_results.csv.')
    args = parser.parse_args()

    try:
        if args.analyze:
            results = analyze_all()
        else:
            results = load_results_from_csv()
            if results is None:
                print("No cached results found. Running full analysis...", flush=True)
                results = analyze_all()

        if results:
            generate_report(results)
    except Exception as e:
        print(f"Script crashed: {e}", flush=True)
        traceback.print_exc()
