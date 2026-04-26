/* SPMS — Chart.js Dashboard Logic */

function getChartColors(count) {
  const palette = [
    'rgba(108, 99, 255, 0.85)',
    'rgba(0, 212, 170, 0.85)',
    'rgba(255, 167, 38, 0.85)',
    'rgba(255, 107, 107, 0.85)',
    'rgba(66, 165, 245, 0.85)',
    'rgba(171, 71, 188, 0.85)',
    'rgba(255, 202, 40, 0.85)',
  ];
  return palette.slice(0, count);
}

function getBorderColors(count) {
  const palette = [
    '#6c63ff', '#00d4aa', '#ffa726', '#ff6b6b',
    '#42a5f5', '#ab47bc', '#ffca28',
  ];
  return palette.slice(0, count);
}

function getBarColor(value) {
  if (value >= 75) return 'rgba(0, 212, 170, 0.85)';
  if (value >= 60) return 'rgba(255, 167, 38, 0.85)';
  return 'rgba(255, 107, 107, 0.85)';
}

/**
 * Render attendance bar chart.
 * @param {string} canvasId — ID of the canvas element
 * @param {Array} data — [{subject, percentage, attended, total}]
 */
function renderAttendanceChart(canvasId, data) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !data.length) return;

  const labels = data.map(d => d.subject.length > 15 ? d.subject.substring(0, 15) + '…' : d.subject);
  const values = data.map(d => d.percentage);
  const colors = values.map(v => getBarColor(v));

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Attendance %',
        data: values,
        backgroundColor: colors,
        borderRadius: 8,
        borderSkipped: false,
        barThickness: 36,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a2e',
          titleFont: { family: 'Outfit', size: 13 },
          bodyFont: { family: 'Inter', size: 12 },
          cornerRadius: 8,
          padding: 12,
          callbacks: {
            label: function(ctx) {
              const d = data[ctx.dataIndex];
              return `${d.attended}/${d.total} classes (${d.percentage}%)`;
            }
          }
        }
      },
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: { font: { family: 'Inter', size: 11 }, callback: v => v + '%' }
        },
        x: {
          grid: { display: false },
          ticks: { font: { family: 'Inter', size: 11 } }
        }
      },
      animation: { duration: 1200, easing: 'easeOutQuart' }
    }
  });
}

/**
 * Render marks comparison chart (grouped bar).
 * @param {string} canvasId
 * @param {Array} data — [{subject, exam_type, obtained, max, percentage}]
 */
function renderMarksChart(canvasId, data) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !data.length) return;

  const subjects = [...new Set(data.map(d => d.subject))];
  const examTypes = [...new Set(data.map(d => d.exam_type))];
  const colors = getChartColors(examTypes.length);
  const borders = getBorderColors(examTypes.length);

  const datasets = examTypes.map((exam, i) => ({
    label: exam,
    data: subjects.map(subj => {
      const match = data.find(d => d.subject === subj && d.exam_type === exam);
      return match ? match.percentage : 0;
    }),
    backgroundColor: colors[i],
    borderColor: borders[i],
    borderWidth: 1,
    borderRadius: 6,
    barThickness: 20,
  }));

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: subjects.map(s => s.length > 12 ? s.substring(0, 12) + '…' : s),
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          labels: { font: { family: 'Inter', size: 11 }, usePointStyle: true, pointStyle: 'circle' }
        },
        tooltip: {
          backgroundColor: '#1a1a2e',
          cornerRadius: 8,
          padding: 12,
        }
      },
      scales: {
        y: {
          beginAtZero: true, max: 100,
          grid: { color: 'rgba(0,0,0,0.05)' },
          ticks: { font: { family: 'Inter', size: 11 }, callback: v => v + '%' }
        },
        x: {
          grid: { display: false },
          ticks: { font: { family: 'Inter', size: 10 } }
        }
      },
      animation: { duration: 1200, easing: 'easeOutQuart' }
    }
  });
}

/**
 * Render attendance doughnut chart.
 */
function renderAttendanceDoughnut(canvasId, attended, total) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const absent = total - attended;
  const pct = total > 0 ? Math.round((attended / total) * 100) : 0;

  new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['Attended', 'Absent'],
      datasets: [{
        data: [attended, absent],
        backgroundColor: ['rgba(0,212,170,0.85)', 'rgba(255,107,107,0.4)'],
        borderWidth: 0,
        cutout: '72%',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: '#1a1a2e', cornerRadius: 8 }
      },
      animation: { duration: 1500, easing: 'easeOutQuart' }
    },
    plugins: [{
      id: 'centerText',
      beforeDraw: function(chart) {
        const { width, height, ctx: c } = chart;
        c.restore();
        c.font = "bold 28px 'Outfit', sans-serif";
        c.fillStyle = '#1a1a2e';
        c.textAlign = 'center';
        c.textBaseline = 'middle';
        c.fillText(pct + '%', width / 2, height / 2);
        c.save();
      }
    }]
  });
}

/**
 * Render risk distribution pie chart.
 */
function renderRiskPie(canvasId, low, medium, high) {
  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  new Chart(ctx, {
    type: 'pie',
    data: {
      labels: ['Low Risk', 'Medium Risk', 'High Risk'],
      datasets: [{
        data: [low, medium, high],
        backgroundColor: ['rgba(0,212,170,0.85)', 'rgba(255,167,38,0.85)', 'rgba(255,107,107,0.85)'],
        borderWidth: 2,
        borderColor: '#fff',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { font: { family: 'Inter', size: 12 }, usePointStyle: true, padding: 16 }
        }
      },
      animation: { duration: 1200 }
    }
  });
}
