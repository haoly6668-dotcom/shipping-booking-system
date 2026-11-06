/* Client-side conveniences only. All authorization and capacity checks run on the server. */
'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const navButton = document.querySelector('[data-toggle-nav]');
  const closeNav = () => { document.body.classList.remove('nav-open'); navButton?.setAttribute('aria-expanded','false'); };
  navButton?.addEventListener('click', () => { const open=document.body.classList.toggle('nav-open'); navButton.setAttribute('aria-expanded',String(open)); });
  document.querySelector('[data-close-nav]')?.addEventListener('click',closeNav);
  document.addEventListener('keydown',e=>{if(e.key==='Escape') closeNav();});
  document.querySelectorAll('[data-dismiss]').forEach(button=>button.addEventListener('click',()=>button.closest('.alert')?.remove()));
  document.querySelector('[data-go-back]')?.addEventListener('click',()=>{if(history.length>1) history.back();else location.assign('/');});

  const bookingForm=document.querySelector('[data-booking-form]');
  if(bookingForm){
    const body=bookingForm.querySelector('[data-item-body]');
    const addButton=bookingForm.querySelector('[data-add-line]');
    const template=document.querySelector('#item-template');
    const voyage=bookingForm.querySelector('[data-voyage]');
    const number=(value)=>{const n=Number(value);return Number.isFinite(n)&&n>0?n:0;};
    const format=(n,d=0)=>n.toLocaleString('zh-CN',{minimumFractionDigits:d,maximumFractionDigits:d});
    const setText=(selector,value)=>{const node=document.querySelector(selector);if(node)node.textContent=value;};
    const update=()=>{
      let boxes=0,teu=0,weight=0;
      const types=new Set();
      const rows=[...body.querySelectorAll('[data-item-row]')];
      rows.forEach((row,index)=>{
        const type=row.querySelector('[data-type]');const quantity=row.querySelector('[data-quantity]');const gross=row.querySelector('[data-weight]');
        const factor=number(type.selectedOptions[0]?.dataset.factor);const count=number(quantity.value);const rowTeu=factor*count;
        type.setCustomValidity(type.value&&types.has(type.value)?'同一箱型只能填写一行，请合并数量。':'');
        if(type.value)types.add(type.value);
        const filled=Boolean(type.value||quantity.value||gross.value);
        [type,quantity,gross].forEach(input=>{input.required=filled;});
        row.querySelector('[data-line-teu]').textContent=factor?format(rowTeu):'—';
        type.setAttribute('aria-label',`第 ${index+1} 行箱型`);quantity.setAttribute('aria-label',`第 ${index+1} 行箱数`);gross.setAttribute('aria-label',`第 ${index+1} 行合计毛重 kg`);
        boxes+=count;teu+=rowTeu;weight+=number(gross.value);
      });
      addButton.disabled=rows.length>=3;
      setText('[data-total-boxes]',format(boxes));setText('[data-total-teu]',format(teu));setText('[data-total-weight]',format(weight,3));
      const option=voyage.selectedOptions[0];const selected=Boolean(voyage.value);
      document.querySelector('[data-voyage-placeholder]').hidden=selected;
      document.querySelector('[data-voyage-preview]').hidden=!selected;
      if(selected){setText('[data-preview-route]',option.dataset.route);setText('[data-preview-teu]',format(Number(option.dataset.teu)));setText('[data-preview-weight]',format(Number(option.dataset.weight),3));setText('[data-preview-cutoff]',option.dataset.cutoff);document.querySelector('[data-capacity-warning]').hidden=!(teu>Number(option.dataset.teu)||weight>Number(option.dataset.weight));}
    };
    addButton.addEventListener('click',()=>{if(body.children.length<3){body.append(template.content.cloneNode(true));update();body.lastElementChild.querySelector('select').focus();}});
    body.addEventListener('click',event=>{const button=event.target.closest('[data-remove-line]');if(!button)return;const row=button.closest('[data-item-row]');if(body.children.length>1)row.remove();else row.querySelectorAll('input,select').forEach(input=>input.value='');update();});
    bookingForm.addEventListener('input',update);bookingForm.addEventListener('change',update);update();
  }
  document.querySelectorAll('form[method="post"]').forEach(form=>{
    form.addEventListener('submit',event=>{
      if(form.dataset.submitting==='true'){event.preventDefault();return;}
      if(form.dataset.confirm&&!window.confirm(form.dataset.confirm)){event.preventDefault();return;}
      form.dataset.submitting='true';
      const button=event.submitter;
      if(button){button.setAttribute('aria-busy','true');setTimeout(()=>{button.disabled=true;},0);}
    });
  });
});
window.addEventListener('pageshow',()=>{document.querySelectorAll('form[data-submitting]').forEach(form=>{delete form.dataset.submitting;form.querySelectorAll('[aria-busy]').forEach(button=>{button.disabled=false;button.removeAttribute('aria-busy');});});});

// Use an explicit timezone so the clock matches shipping schedules.
document.addEventListener('DOMContentLoaded', () => {
  const clock = document.querySelector('[data-live-clock]');
  if (!clock) return;
  const timeFormat = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hourCycle: 'h23'
  });
  const dateFormat = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', weekday: 'short'
  });
  const updateClock = () => {
    const now = new Date();
    const time = clock.querySelector('[data-clock-time]');
    time.textContent = timeFormat.format(now);
    time.dateTime = now.toISOString();
    clock.querySelector('[data-clock-date]').textContent = dateFormat.format(now);
  };
  updateClock();
  setInterval(updateClock, 1000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) updateClock(); });
});

// Progressive enhancement: without JS every business section stays readable.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('[data-workspace-tabs]').forEach(workspace => {
    const bar = workspace.querySelector('[role="tablist"]');
    const tabs = [...bar.querySelectorAll('[role="tab"]')];
    const selectTab = tab => {
      tabs.forEach(item => {
        const selected = item === tab;
        item.setAttribute('aria-selected', String(selected));
        item.tabIndex = selected ? 0 : -1;
        const panel = document.getElementById(item.getAttribute('aria-controls'));
        panel.hidden = !selected;
        panel.setAttribute('role', 'tabpanel');
        panel.setAttribute('aria-labelledby', item.id);
        panel.tabIndex = 0;
      });
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => selectTab(tab));
      tab.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = tabs.length - 1;
        else return;
        event.preventDefault();
        selectTab(tabs[next]);
        tabs[next].focus();
      });
    });
    if (tabs.length > 1) {
      workspace.classList.add('tabs-enhanced');
      bar.hidden = false;
      selectTab(tabs.find(tab => tab.getAttribute('aria-selected') === 'true') || tabs[0]);
    }
  });
});
