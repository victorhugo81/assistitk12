// **************************
// dropdown filters
// **************************
  document.getElementById('site_filter').addEventListener('change', function(event) {
      updateURLParameter('site_id', event.target.value);
  });

  document.getElementById('year').addEventListener('change', function(event) {
      updateURLParameter('year', event.target.value);
  });

  function updateURLParameter(param, value) {
      let url = new URL(window.location.href);
      if (value) { // Check if a value is selected
          url.searchParams.set(param, value);
      } else { // Handle 'All' option by deleting the parameter
          url.searchParams.delete(param);
      }
      window.location.href = url.toString();
  }

  function updateFilters() {
    const siteId = document.getElementById('site_filter').value;
    const year = document.getElementById('year').value;
    const params = new URLSearchParams(window.location.search);
    if (siteId) {
        params.set('site_id', siteId);
    } else {
        params.delete('site_id');
    }
    if (year) {
        params.set('year', year);
    } else {
        params.delete('year');
    }
    window.location.search = params.toString();
  }





// **************************
// Monthly BarChart
// **************************
var ctx2 = document.getElementById("chart-line").getContext("2d");
var primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--bs-main-color-primary').trim();

new Chart(ctx2, {
  type: "line",
  data: {
      labels: months,
      datasets: [{
          label: "Tickets",
          tension: 0,
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: primaryColor,
          pointBorderColor: "transparent",
          borderColor: primaryColor,
          backgroundColor: "transparent",
          fill: true,
          data: counts,
          maxBarThickness: 6
      }],
  },
  options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
          legend: {
              display: false,
          },
          tooltip: {
              callbacks: {
                  title: function(context) {
                      const fullMonths = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
                      return fullMonths[context[0].dataIndex];
                  }
              }
          }
      },
      interaction: {
          intersect: false,
          mode: 'index',
      },
      scales: {
          y: {
              grid: {
                  drawBorder: false,
                  display: true,
                  drawOnChartArea: true,
                  drawTicks: false,
                  borderDash: [4, 4],
                  color: '#e5e5e5'
              },
              ticks: {
                  display: true,
                  color: '#737373',
                  padding: 10,
                  font: {
                      size: 12,
                      lineHeight: 2
                  },
              }
          },
          x: {
              grid: {
                  drawBorder: false,
                  display: false,
                  drawOnChartArea: false,
                  drawTicks: false,
                  borderDash: [5, 5]
              },
              ticks: {
                  display: true,
                  color: '#737373',
                  padding: 10,
                  font: {
                      size: 12,
                      lineHeight: 2
                  },
              }
          },
      },
  },
});



// **************************
// Weekly BarChart
// **************************
var ctx = document.getElementById("chart-bars").getContext("2d");
// Dynamically fetch the CSS variable for the primary color
var primaryColor = getComputedStyle(document.documentElement).getPropertyValue('--bs-main-color-primary').trim();

new Chart(ctx, {
type: "bar",
data: {
  labels: weekdays,
  datasets: [{
    label: "Views",
    tension: 0.4,
    borderWidth: 0,
    borderRadius: 4,
    borderSkipped: false,
    backgroundColor: primaryColor,
    data: weekday_counts,
    barThickness: 'flex'
  }, ],
},
options: {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      display: false,
    }
  },
  interaction: {
    intersect: false,
    mode: 'index',
  },
  scales: {
    y: {
      grid: {
        drawBorder: false,
        display: true,
        drawOnChartArea: true,
        drawTicks: false,
        borderDash: [5, 5],
        color: '#e5e5e5'
      },
      ticks: {
        suggestedMin: 0,
        suggestedMax: 500,
        beginAtZero: true,
        padding: 10,
        font: {
          size: 14,
          lineHeight: 2
        },
        color: "#737373"
      },
    },
    x: {
      grid: {
        drawBorder: false,
        display: false,
        drawOnChartArea: false,
        drawTicks: false,
        borderDash: [5, 5]
      },
      ticks: {
        display: true,
        color: '#737373',
        padding: 10,
        font: {
          size: 14,
          lineHeight: 2
        },
      }
    },
  },
},
});
