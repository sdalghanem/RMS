(() => {
  const canvas=document.getElementById('admin-income-chart');
  if(!canvas)return;
  const labels=JSON.parse(document.getElementById('admin-income-labels').textContent);
  const values=JSON.parse(document.getElementById('admin-income-values').textContent);
  const money=new Intl.NumberFormat('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  const body=document.getElementById('admin-chart-values');
  labels.forEach((label,i)=>{const row=document.createElement('tr');const month=document.createElement('th');month.scope='row';month.textContent=label;const amount=document.createElement('td');amount.textContent=money.format(values[i]);amount.dir='ltr';row.append(month,amount);body.append(row);});
  if(!values.some(value=>value>0)){canvas.hidden=true;document.getElementById('admin-chart-empty').hidden=false;return;}
  if(typeof Chart==='undefined'){canvas.hidden=true;document.querySelector('.fd-chart-data').open=true;return;}
  new Chart(canvas,{type:'bar',data:{labels,datasets:[{label:'الإيرادات',data:values,backgroundColor:'#526fc2',hoverBackgroundColor:'#354f9a',borderRadius:5,maxBarThickness:32}]},options:{responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:{display:false},tooltip:{rtl:true,titleFont:{family:'IBM Plex Sans Arabic'},bodyFont:{family:'IBM Plex Sans Arabic'},callbacks:{label:context=>money.format(context.parsed.y)+' ر.س'}}},scales:{x:{grid:{display:false},ticks:{font:{family:'IBM Plex Sans Arabic'},color:'#65738a'}},y:{beginAtZero:true,border:{display:false},grid:{color:'#edf0f5'},ticks:{color:'#65738a',font:{family:'IBM Plex Sans Arabic'},callback:value=>new Intl.NumberFormat('ar-SA-u-nu-latn',{notation:'compact'}).format(value)}}}}});
})();
