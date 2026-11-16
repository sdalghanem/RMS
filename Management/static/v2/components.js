/* UI-only safeguards: server validation remains authoritative. */
(() => {
  'use strict';
  const region = document.getElementById('v2-toasts');
  const toast = (message, kind = 'info') => {
    if (!region) return;
    const item = document.createElement('div'); item.className = 'v2-toast'; item.dataset.kind = kind;
    item.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    const text = document.createElement('span'); text.textContent = String(message);
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label','إغلاق التنبيه'); close.onclick = () => item.remove();
    item.append(text,close);region.append(item);
    // Messages persist until dismissed, including confirmed financial results.
  };
  window.KafalatUI = {toast};
  window.alert = message => toast(message,'error');
  document.querySelectorAll('form[onsubmit]').forEach(form=>{
    const match=form.getAttribute('onsubmit').match(/return\s+confirm\((['"])(.*?)\1\)/);
    if(match){form.dataset.v2Confirm=match[2];form.removeAttribute('onsubmit');}
  });
  document.querySelectorAll('#rms-messages .rms-alert, #rms-messages .alert, .container.mt-3 > .alert').forEach(el => {
    const kind = ['error','danger','warning','success','info'].find(x=>el.className.includes(x)) || 'info';
    toast(el.textContent.replace('×','').trim(),kind==='danger'?'error':kind);el.remove();
  });
  const dialog=document.getElementById('v2-dialog');
  let current=null,trigger=null,confirmed=null;
  const financial= form=>form.method.toLowerCase()==='post' && /allocate|fund-to-main|main-to-sub|release|disbursement|renew|sponsorship|invoices/.test(new URL(form.action||location.href,location.href).pathname);

  document.addEventListener('submit',event=>{
    const form=event.target;if(!(form instanceof HTMLFormElement)||form.method==='dialog'||(!financial(form)&&!form.dataset.v2Confirm))return;

    if(confirmed===form){
      confirmed=null;
      return;
    }
    event.preventDefault();if(!form.reportValidity())return;
    current=form;trigger=event.submitter||document.activeElement;
    const details=[];
    if(form.dataset.v2Confirm)details.push(form.dataset.v2Confirm);
    const formValues=new FormData(form);
    const beneficiaries=formValues.getAll('beneficiary_ids[]'),amounts=formValues.getAll('amounts[]');
    if(beneficiaries.length){
      details.push('عدد المستفيدين: '+beneficiaries.length);
      beneficiaries.forEach((id,i)=>{
        const control=[...form.querySelectorAll('[name="beneficiary_ids[]"]')].find(el=>el.value===id);
        const name=control?.closest('tr')?.dataset.beneficiaryName||('المستفيد '+id);
        details.push(name+' — '+(amounts[i]||'راجع المبلغ')+' ر.س');
      });
    }
    for(const [name,value] of formValues){
      if(name==='beneficiary_ids[]'||name==='amounts[]')continue;
      if(/csrf|password|token/i.test(name)||value instanceof File||!value)continue;
      const control=form.elements.namedItem(name);
      const label=control?.labels?.[0]?.textContent.trim()||name;
      const shown=control instanceof HTMLSelectElement ? control.selectedOptions[0]?.textContent.trim() : String(value);
      details.push(label+': '+shown);
    }
    document.getElementById('v2-dialog-details').textContent=details.join('\n');
    dialog.returnValue='cancel';
    dialog.showModal();
  },true);
  dialog?.addEventListener('close',()=>{
    trigger?.focus();
    if(dialog.returnValue==='confirm'&&current){confirmed=current;current.requestSubmit(trigger instanceof HTMLButtonElement&&trigger.type==='submit'&&trigger.form===current?trigger:undefined);}
    current=null;
  });
  dialog?.addEventListener('keydown',event=>{
    if(event.key!=='Tab')return;
    const items=[...dialog.querySelectorAll('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')].filter(el=>el.getClientRects().length);
    if(!items.length){event.preventDefault();return;}
    if(event.shiftKey&&document.activeElement===items[0]){event.preventDefault();items.at(-1).focus();}
    else if(!event.shiftKey&&document.activeElement===items.at(-1)){event.preventDefault();items[0].focus();}
  });
  document.querySelectorAll('table').forEach(table=>{if(!table.closest('.table-responsive')){const wrap=document.createElement('div');wrap.className='table-responsive';table.before(wrap);wrap.append(table);}});
  document.querySelectorAll('.table-responsive').forEach(el=>{el.tabIndex=0;el.setAttribute('role','region');el.setAttribute('aria-label','جدول بيانات قابل للتمرير');});
  document.querySelectorAll('input[type=search]').forEach(el=>{if(!el.labels?.length&&!el.getAttribute('aria-label'))el.setAttribute('aria-label',el.placeholder||'بحث');});
  const spendButton=document.getElementById('submit-btn');
  if(spendButton){
    const help=document.createElement('p');help.id='v2-spend-help';help.className='text-muted small';help.setAttribute('role','status');spendButton.after(help);spendButton.setAttribute('aria-describedby',help.id);
    const update=()=>{help.textContent=spendButton.disabled?'اختر برنامجًا ومستفيدًا وأدخل مبلغًا موجبًا ضمن الرصيد المتاح.':'راجع تفاصيل المستفيدين والمبالغ قبل تأكيد الصرف.';};
    new MutationObserver(update).observe(spendButton,{attributes:true,attributeFilter:['disabled']});update();
    document.getElementById('total-amount')?.setAttribute('aria-live','polite');
  }
  // Preserve the exact list URL (filters and page) for same-origin detail navigation.
  if(location.search)sessionStorage.setItem('kafalat-v2-results:'+location.pathname,location.pathname+location.search);
  document.querySelectorAll('[data-v2-back]').forEach(a=>{const path=new URL(a.href,location.href).pathname;const saved=sessionStorage.getItem('kafalat-v2-results:'+path);if(saved&&new URL(saved,location.href).pathname===path)a.href=saved;});
})();
