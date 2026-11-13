"""Persistent local-browser inspector and safe DOM collection worker."""
from __future__ import annotations

import queue
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlsplit, quote
import re

from app.collectors.browser_runtime import launch_persistent_context
from app.core.jalali import jalali_to_gregorian


_INIT_SCRIPT = r'''(() => {
  if (window.__structuraInspectorInstalled || window.top !== window.self) return;
  window.__structuraInspectorInstalled = true;
  const cssEscape = value => window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  function selectorFor(el, requireUnique = true) {
    if (!el || el.nodeType !== 1) return '';
    for (const a of ['data-message-id','data-testid','data-test-id','data-qa','data-cy']) {
      const v = el.getAttribute(a);
      if (v) { const s = `[${a}="${String(v).replace(/"/g,'\\"')}"]`; try { if (!requireUnique || document.querySelectorAll(s).length === 1) return s; } catch {} }
    }
    if (el.id && !/\d{4,}/.test(el.id)) { const s = '#' + cssEscape(el.id); try { if (!requireUnique || document.querySelectorAll(s).length === 1) return s; } catch {} }
    const parts = []; let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement && parts.length < 8) {
      let part = node.tagName.toLowerCase();
      const classes = [...node.classList].filter(x => /^[a-zA-Z_-][\w-]*$/.test(x) && !/(?:^|[-_])[a-f0-9]{7,}|\d{4,}/i.test(x)).slice(0,2);
      if (classes.length) part += classes.map(x => '.' + cssEscape(x)).join('');
      else if (node.parentElement) { const siblings = [...node.parentElement.children].filter(x => x.tagName === node.tagName); if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node)+1})`; }
      parts.unshift(part);
      const candidate = parts.join(' > ');
      try { if (!requireUnique || document.querySelectorAll(candidate).length === 1) return candidate; } catch {}
      node = node.parentElement;
    }
    return parts.join(' > ');
  }
  const ignored = el => !el || el.closest?.('#__structura_inspector_ui,#__structura_hover_layer,#__structura_inspector_menu');
  const layer = document.createElement('div');
  layer.id = '__structura_hover_layer';
  layer.style.cssText = 'position:fixed;z-index:2147483645;pointer-events:none;border:2px solid #9c8cff;background:rgba(156,140,255,.10);display:none;box-sizing:border-box;border-radius:3px;';
  const badge = document.createElement('div');
  badge.id = '__structura_inspector_ui';
  badge.style.cssText = 'position:fixed;z-index:2147483647;top:12px;right:12px;pointer-events:auto;display:flex;align-items:center;gap:8px;flex-wrap:wrap;background:#17152a;color:#eeeaff;border:1px solid #8778df;border-radius:10px;padding:8px 10px;font:600 12px/1.4 system-ui,sans-serif;box-shadow:0 4px 20px #0008;max-width:min(560px,calc(100vw - 24px));';
  const label = document.createElement('span'); label.textContent='AGENT SHADI · DOM INSPECTOR';
  const mode = document.createElement('button'); mode.type='button'; mode.textContent='Click select: OFF';
  mode.style.cssText='border:1px solid #6c61aa;background:#2a2545;color:#eeeaff;border-radius:7px;padding:6px 9px;font:600 12px system-ui;cursor:pointer;';
  const hint = document.createElement('span'); hint.textContent='Right-click an element for Select'; hint.style.cssText='opacity:.82;font-weight:500;';
  badge.append(label,mode,hint);
  const menu = document.createElement('div'); menu.id='__structura_inspector_menu';
  menu.style.cssText='position:fixed;z-index:2147483647;display:none;min-width:170px;padding:6px;background:#17152a;border:1px solid #8778df;border-radius:9px;box-shadow:0 8px 28px #0009;font:600 12px system-ui,sans-serif;';
  const menuButton = (caption, action) => { const b=document.createElement('button');b.type='button';b.textContent=caption;b.style.cssText='display:block;width:100%;text-align:left;border:0;background:transparent;color:#eeeaff;border-radius:6px;padding:8px;cursor:pointer;font:inherit;';b.addEventListener('mouseenter',()=>b.style.background='#38315d');b.addEventListener('mouseleave',()=>b.style.background='transparent');b.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();action();menu.style.display='none';});return b; };
  let contextTarget = null;
  let selectionMode = false;
  let selectionTarget = 'element';
  const setMode = value => { selectionMode=!!value; mode.textContent=`Click select: ${selectionMode?'ON':'OFF'}`; mode.style.background=selectionMode?'#174d3b':'#2a2545'; mode.style.borderColor=selectionMode?'#55d6a4':'#6c61aa'; hint.textContent=selectionMode?`Pick ${selectionTarget.replace('_',' ')} · click an element · Esc cancels`:'Right-click an element for Select'; };
  // The connector workbench can arm a field-specific picker through Playwright.
  // This keeps the user in a guided setup flow instead of copying HTML/selectors.
  window.__structuraSetSelectionMode = target => {
    const allowed = new Set(['root','text','sender','timestamp','message_id','attachment','element']);
    selectionTarget = allowed.has(String(target||'')) ? String(target) : 'element';
    setMode(true);
    return {ok:true,target:selectionTarget};
  };
  const attach = () => { if (!document.documentElement) return; for (const el of [layer,badge,menu]) if (!el.isConnected) document.documentElement.appendChild(el); };
  // add_init_script can execute before <html> exists. Never pass a null root
  // to MutationObserver.observe(); watch the Document until documentElement appears.
  const rootObserver = new MutationObserver(attach);
  const observeRoot = () => {
    const root = document.documentElement;
    if (!root || root.nodeType !== 1) return false;
    try { rootObserver.observe(root,{childList:true}); attach(); return true; } catch { return false; }
  };
  if (!observeRoot()) {
    const documentObserver = new MutationObserver(() => {
      if (observeRoot()) documentObserver.disconnect();
    });
    documentObserver.observe(document,{childList:true,subtree:true});
  }
  mode.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();setMode(!selectionMode);});
  const stableClasses = el => [...(el?.classList||[])].filter(x => /^[a-zA-Z_-][\w-]*$/.test(x) && !/(?:^|[-_])[a-f0-9]{7,}|\d{4,}/i.test(x) && !/^(active|selected|open|closed|visible|hidden|loading|hover|focus|disabled|checked|unread|pinned)$/i.test(x));
  const selectorSegment = el => {
    if (!el || el.nodeType!==1) return '';
    let part=el.tagName.toLowerCase();
    const classes=stableClasses(el);
    if(classes.length) part+=classes.slice(0,4).map(x=>'.'+cssEscape(x)).join('');
    return part;
  };
  const sameFamily = (a,b) => {
    if(!a||!b||a.tagName!==b.tagName)return false;
    const ac=stableClasses(a),bc=stableClasses(b);
    if(!ac.length&&!bc.length)return false;
    return ac.some(x=>bc.includes(x));
  };
  const repeatedGroupFor = el => {
    let node=el;
    for(let depth=0;node&&node.parentElement&&depth<14;depth++,node=node.parentElement){
      const peers=[...node.parentElement.children].filter(peer=>sameFamily(peer,node));
      if(peers.length>=2){
        const own=stableClasses(node);
        const shared=own.filter(c=>peers.every(peer=>stableClasses(peer).includes(c)));
        if(shared.length){
          const selector=node.tagName.toLowerCase()+shared.slice(0,4).map(x=>'.'+cssEscape(x)).join('');
          let count=0;try{count=document.querySelectorAll(selector).length;}catch{}
          if(count>=2)return {node,selector,count,peers:peers.length};
        }
      }
    }
    return null;
  };
  const selectorWithin = (root, target, rootSelector) => {
    if(!root||!target||root===target)return ':root';
    const path=[];let node=target;
    while(node&&node!==root&&path.length<12){
      const parent=node.parentElement;if(!parent)return '';
      const sameTag=[...parent.children].filter(x=>x.tagName===node.tagName);
      path.unshift({tag:node.tagName.toLowerCase(),index:sameTag.indexOf(node)+1});
      node=parent;
    }
    if(node!==root||!path.length)return '';
    let parents=[];try{parents=[...document.querySelectorAll(rootSelector)].slice(0,80);}catch{}
    if(!parents.length)parents=[root];
    const parts=[];
    for(const step of path){
      const equivalents=parents.map(parent=>[...parent.children].filter(x=>x.tagName.toLowerCase()===step.tag)[step.index-1]).filter(Boolean);
      if(!equivalents.length)return '';
      let shared=stableClasses(equivalents[0]).filter(cls=>equivalents.every(el=>stableClasses(el).includes(cls)));
      let part=step.tag+(shared.length?shared.slice(0,4).map(x=>'.'+cssEscape(x)).join(''):`:nth-of-type(${step.index})`);
      const needsIndex=equivalents.some(el=>[...el.parentElement.children].filter(x=>x.tagName===el.tagName&&selectorSegment(x)===selectorSegment(el)).length>1);
      if(needsIndex&&!part.includes(':nth-of-type'))part+=`:nth-of-type(${step.index})`;
      parts.push(part);parents=equivalents;
    }
    return parts.join(' > ');
  };
  const makePayload = el => {
    const attrs={}; for (const a of [...el.attributes].slice(0,35)) attrs[a.name]=a.value;
    const repeated=repeatedGroupFor(el);
    const rootNode=repeated?.node||el;
    const rootSelector=repeated?.selector||selectorSegment(el)||selectorFor(el);
    let rootCount=0;try{rootCount=document.querySelectorAll(rootSelector).length;}catch{}
    const fieldSelector=selectorWithin(rootNode,el,rootSelector)|| (rootNode===el?':root':selectorFor(el,false));
    return {selector:selectorFor(el),relative_selector:fieldSelector,field_selector:fieldSelector,root_selector:rootSelector,message_root_selector:rootSelector,root_tag:rootNode.tagName.toLowerCase(),repeated_count:rootCount,repeated_siblings:repeated?.peers||1,selected_for:selectionTarget,tag:el.tagName.toLowerCase(),text:(el.innerText||el.textContent||'').trim().slice(0,1000),outer_html:el.outerHTML.slice(0,30000),attributes:attrs,selected_at:new Date().toISOString()};
  };
  const selectElement = el => {
    if (!el || el.nodeType !== 1 || ignored(el)) return;
    const payload=makePayload(el);
    hint.textContent='Saving selection…';
    if (typeof window.__structuraSelect !== 'function') {
      hint.textContent='Selection bridge unavailable · reload this browser tab';
      mode.textContent='Selection failed';
      return;
    }
    Promise.resolve(window.__structuraSelect(payload)).then(result=>{
      if (!result || result.ok !== true) throw new Error(result?.error || 'The application did not acknowledge this selection');
      layer.style.borderColor='#5bd6a4'; layer.style.background='rgba(91,214,164,.12)';
      mode.textContent='Selected ✓';
      hint.textContent=`Saved to Agent Shadi · ${payload.tag} · ${payload.selector}`;
      setMode(false);
      mode.textContent='Selected ✓';
      setTimeout(()=>{if(!selectionMode)mode.textContent='Click select: OFF';},2200);
    }).catch(error=>{
      mode.textContent='Selection failed';
      hint.textContent=`Could not send selection · ${String(error?.message||error).slice(0,120)}`;
    });
  };
  const nearestRepeatedContainer = el => repeatedGroupFor(el)?.node || el;
  document.addEventListener('mousemove',e=>{
    if (ignored(e.target)) return;
    const el=e.target; if (!el?.getBoundingClientRect) return;
    const r=el.getBoundingClientRect(); layer.style.display='block'; layer.style.left=r.left+'px'; layer.style.top=r.top+'px'; layer.style.width=r.width+'px'; layer.style.height=r.height+'px';
    if (selectionMode) hint.textContent=`Click to select ${el.tagName.toLowerCase()} · Esc cancels`;
  },true);
  document.addEventListener('click',e=>{
    if (ignored(e.target)) return;
    if (selectionMode || e.altKey) { e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();selectElement(e.target); }
  },true);
  document.addEventListener('contextmenu',e=>{
    if (ignored(e.target)) return;
    e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();
    contextTarget=e.target;
    menu.replaceChildren(
      menuButton('Select this element',()=>selectElement(contextTarget)),
      menuButton('Select parent element',()=>selectElement(contextTarget?.parentElement)),
      menuButton('Select nearest repeated item',()=>selectElement(nearestRepeatedContainer(contextTarget))),
      menuButton('Select grandparent',()=>selectElement(contextTarget?.parentElement?.parentElement)),
      menuButton('Cancel',()=>{})
    );
    menu.style.display='block';
    menu.style.left=Math.max(8,Math.min(e.clientX,window.innerWidth-210))+'px';
    menu.style.top=Math.max(8,Math.min(e.clientY,window.innerHeight-210))+'px';
  },true);
  document.addEventListener('pointerdown',e=>{if(!ignored(e.target)&&menu.style.display==='block'&&!menu.contains(e.target))menu.style.display='none';},true);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){menu.style.display='none';layer.style.display='none';setMode(false);}},true);
  setMode(false);
})();'''

_OPEN_CHANNEL_SCRIPT = r'''async ({name, targetUrl, targetUrlNavigated, username, platformId, identitySelector, identityAttribute, searchInputSelector, searchResultSelector, messageSelector, textSelector}) => {
  const clean = s => String(s || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase();
  const wanted = clean(name);
  const normalizeUsername = raw => {
    const value = String(raw || '').trim();
    if (!value) return '';
    try {
      if (/^https?:\/\//i.test(value)) {
        const u = new URL(value);
        const parts = [u.pathname, u.hash].join('/').split(/[\/?#&=]+/).filter(Boolean);
        const candidate = parts.map(part => decodeURIComponent(part).replace(/^@+/, '').toLocaleLowerCase()).find(part => part && !['channel','user','c'].includes(part));
        if (candidate) return candidate;
      }
    } catch {}
    return clean(value).replace(/^@+/, '').replace(/^\/+|\/+$/g, '');
  };
  const wantedUser = normalizeUsername(username);
  const wantedId = String(platformId || '').trim();
  const visible = el => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none');
  const normUrl = raw => {
    try { const u = new URL(raw, location.href); u.username=''; u.password=''; u.pathname=u.pathname.replace(/\/+$/,'') || '/'; return `${u.origin}${u.pathname}${u.hash}`.toLocaleLowerCase(); }
    catch { return ''; }
  };
  const urlContainsUsername = raw => {
    if (!wantedUser) return false;
    try {
      const u = new URL(raw, location.href);
      const rawParts = [...u.pathname.split('/'), ...u.hash.split(/[\/?#&=]+/)];
      return rawParts.map(part => { try { return decodeURIComponent(part).replace(/^@+/, '').toLocaleLowerCase(); } catch { return String(part).replace(/^@+/, '').toLocaleLowerCase(); } }).some(part => part === wantedUser);
    } catch { return false; }
  };
  const currentUrl = location.href;
  // A URL/hash is routing intent, not proof by itself. It must agree with a
  // real, non-generic active header; exact platform ID + requested title can
  // prove identity even before the message-root selector has been mapped.
  const targetUrlMatch = !!(targetUrl && normUrl(currentUrl) === normUrl(targetUrl));
  const urlHasUser = !!(wantedUser && urlContainsUsername(currentUrl));
  const genericTitles = new Set(['search','جستجو','جست و جو','چت ها','گفتگوها','chats','contacts','settings','تنظیمات','مخاطبین']);
  const isGenericTitle = value => genericTitles.has(clean(value));
  const activeMessageCount = () => {
    const countFor = selector => { try { return [...document.querySelectorAll(selector)].filter(el=>visible(el) && !el.closest('.chatlist, [role="list"] .chatlist-chat, .search-results')).length; } catch { return 0; } };
    if (messageSelector) {
      const exact=countFor(messageSelector); if(exact) return exact;
      const simple=String(messageSelector).trim().match(/^([a-zA-Z][\w-]*)?((?:\.[a-zA-Z_-][\w-]*)+)$/);
      if(simple){const tag=simple[1]||'',classes=simple[2].split('.').filter(Boolean);for(let keep=classes.length-1;keep>=1;keep--){const count=countFor(tag+classes.slice(0,keep).map(c=>'.'+c).join(''));if(count)return count;}}
    }
    // Diagnostic fallback: message presence is independent of the saved root selector.
    for (const selector of ['div.message.spoilers-container','.message.spoilers-container','[data-message-id]','div[data-testid*="message"]']) { const count=countFor(selector); if(count) return count; }
    return 0;
  };
  // Scope identity evidence to conversation-header regions. Broad `main` scans
  // accidentally include search results, sidebar previews and message mentions.
  const activeHeaderNodes = () => [...document.querySelectorAll(
    '.chat-header, .chat-info, .topbar, .conversation-header, [class*="chat-header"], [data-testid*="conversation"], [data-testid*="channel"]'
  )].filter(visible).filter(el => !el.closest('.chatlist, [role="list"] .chatlist-chat, .search-results, [data-testid*="search-result"]'));
  const belongsToActiveHeader = el => activeHeaderNodes().some(host => host === el || host.contains(el));
  const readIdentityNode = el => {
    if (!el) return '';
    if (identityAttribute === 'textContent') return clean(el.textContent);
    if (identityAttribute === 'innerText') return clean(el.innerText || el.textContent);
    return String(el.getAttribute(identityAttribute) || '').trim();
  };
  const identitySelectorEvidence = () => {
    if (!identitySelector) return [];
    let nodes=[]; try { nodes=[...document.querySelectorAll(identitySelector)].filter(el=>visible(el) && !el.closest('.chatlist, .search-results, [data-testid*="search-result"]') && belongsToActiveHeader(el)); } catch { return []; }
    return nodes.slice(0,20).map(el=>({value:readIdentityNode(el),text:clean(el.innerText||el.textContent).slice(0,160)})).filter(x=>x.value);
  };
  const activeIdValues = () => {
    const nodes=[];
    for (const host of activeHeaderNodes()) {
      if (host.matches?.('[data-peer-id]')) nodes.push(host);
      nodes.push(...host.querySelectorAll('[data-peer-id]'));
    }
    return [...new Set([...new Set(nodes)].filter(el=>visible(el) && !el.closest('.chatlist')).map(el=>String(el.getAttribute('data-peer-id')||'').trim()).filter(Boolean))];
  };
  const activeUserValues = () => {
    const vals=[];
    for (const host of activeHeaderNodes()) {
      const nodes=[host,...host.querySelectorAll('[data-username], [data-user], .username-eng, [class~="username"]')].slice(0,80);
      for (const el of nodes) vals.push(String(el.getAttribute('data-username')||''),String(el.getAttribute('data-user')||''),clean(el.innerText||el.textContent||''));
      // Only the header's own link is considered. Descendant links elsewhere in
      // the page may be message mentions or unrelated navigation links.
      if (host.matches('a[href]')) vals.push(String(host.getAttribute('href')||''));
    }
    return vals.filter(Boolean).map(clean);
  };
  const headerTexts = () => {
    const selector=[
      '.chat-header .peer-title', '.chat-header .user-title', '.chat-info .peer-title', '.chat-info .user-title',
      '.topbar .peer-title', '.topbar .user-title', '.conversation-header .peer-title',
      '[data-testid*="conversation-title"]', '[data-testid*="channel-title"]',
      '.chat-header h1', '.chat-header h2', '.chat-info h1', '.topbar h1', 'header h1', 'header h2', 'h1'
    ].join(',');
    const candidates=[...document.querySelectorAll(selector)].filter(visible).filter(el=>!el.closest('.chatlist, .search-results, [data-testid*="search-result"]'));
    const values=candidates.map(x=>clean(x.innerText||x.textContent||x.getAttribute('title')||x.getAttribute('aria-label'))).filter(Boolean);
    return [...new Set(values)].sort((a,b)=>Number(isGenericTitle(a))-Number(isGenericTitle(b)));
  };
  const discoverMessageRootCandidates = () => {
    const selectors=['[data-message-id]','div[data-testid*=\"message\"]','div.message.spoilers-container','.message.spoilers-container','div[class*=\"bubble-content\"]','div.message','article[class*=\"message\"]','li[class*=\"message\"]'];
    const output=[];
    for(const selector of selectors){
      let nodes=[];try{nodes=[...document.querySelectorAll(selector)];}catch{continue;}
      const usable=nodes.filter(el=>visible(el)&&!el.closest('.chatlist, [role=\"list\"] .chatlist-chat, .search-results')&&(()=>{try{const field=(textSelector?el.querySelector(textSelector):null)||el.querySelector('.translatable-message,[data-message-text],.message-text')||el;return !!field&&String(field.innerText||field.textContent||'').trim().length>0;}catch{return false;}})());
      if(usable.length>=2)output.push({selector,count:usable.length});
    }
    return output.sort((a,b)=>b.count-a.count).slice(0,6);
  };
  const inspectCurrent = () => {
    const selectorValues=identitySelectorEvidence().map(x=>x.value);
    const ids=activeIdValues();
    const users=activeUserValues();
    const titles=headerTexts();
    const activeTitle=titles[0]||'';
    const titleVerified=!!(wanted && titles.some(t=>t===wanted || t.includes(wanted)));
    const messageCount=activeMessageCount();
    const exactIdInHeader=!!(wantedId && ids.includes(wantedId));
    const nonGenericActiveTitle=!!activeTitle&&!isGenericTitle(activeTitle);
    // A matching ID inside a recognized active header plus the exact requested
    // title is sufficient to verify conversation identity. Message-root mapping
    // is a separate collector concern and may legitimately still be incomplete.
    const visibleExactPeerId=!!(wantedId && [...document.querySelectorAll('[data-peer-id]')].some(el=>visible(el)&&String(el.getAttribute('data-peer-id')||'').trim()===wantedId));
    const headerIdentityVerified=(exactIdInHeader|| (targetUrlMatch&&visibleExactPeerId))&&titleVerified&&nonGenericActiveTitle;
    const activeConversation=nonGenericActiveTitle&&(messageCount>0||headerIdentityVerified);
    const idVerified=!!(wantedId && exactIdInHeader && nonGenericActiveTitle && (titleVerified || messageCount>0));
    const exactUserValue = value => {
      const normalized=normalizeUsername(value);
      return normalized===wantedUser || urlContainsUsername(value);
    };
    const userSelectorVerified=selectorValues.some(exactUserValue);
    const userHeaderVerified=users.some(exactUserValue);
    const userVerified=!!(wantedUser && activeConversation && (userSelectorVerified || userHeaderVerified || (urlHasUser&&titleVerified)));
    const routeVerified=targetUrlMatch && activeConversation && (titleVerified || exactIdInHeader);
    const titleAndContentVerified=titleVerified && messageCount>0;
    const verified = idVerified || userVerified || routeVerified || titleAndContentVerified;
    const method=idVerified?'platform_id_and_active_title':routeVerified?'target_url_and_verified_header':userVerified?(urlHasUser?'username_and_verified_header':'username'):titleAndContentVerified?'display_name_and_active_conversation':'';
    return {verified,method,title_verified:titleVerified,active_title:activeTitle,active_ids:ids.slice(0,8),active_message_count:messageCount,active_conversation:activeConversation,header_identity_verified:headerIdentityVerified,message_root_candidates:discoverMessageRootCandidates()};
  };
  const waitForCurrentIdentity = async (maxMs=5000) => {
    let state=inspectCurrent(); const deadline=Date.now()+maxMs;
    while(!state.verified && Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,250));state=inspectCurrent();}
    return state;
  };
  let current=inspectCurrent();
  if(!current.verified && targetUrl && (targetUrlMatch || targetUrlNavigated)) current=await waitForCurrentIdentity(5000);
  if(current.verified) return {ok:true,already_open:true,identity_verified:true,identity_method:current.method,active_title:current.active_title,active_ids:current.active_ids,active_message_count:current.active_message_count,active_conversation:current.active_conversation,message_root_candidates:current.message_root_candidates};
  if(targetUrl && !targetUrlMatch && !targetUrlNavigated) return {ok:true,navigation_required:true,identity_verified:false,current_identity:current};
  // If the browser is already on the requested route (or the configured
  // username route), do not search the whole page. A generic 'Search' header
  // means the application has not yet proven that the target chat is open.
  if(targetUrlMatch || urlHasUser) return {ok:false,reason:'target_route_loaded_but_active_conversation_not_detected',requested_target_url:targetUrl,current_identity:current,current_url:location.href};
  if(!wanted && !wantedUser && !wantedId) return {ok:true,skipped:true,reason:'no_channel_identity',identity_verified:false};
  let input=null;
  if(searchInputSelector){try{input=document.querySelector(searchInputSelector);}catch{}if(!visible(input))input=null;}
  if(!input){
    const candidates=[...document.querySelectorAll('input,[role="searchbox"],[contenteditable="true"]')].filter(visible).filter(el=>{
      const hint=clean([el.getAttribute('placeholder'),el.getAttribute('aria-label'),el.getAttribute('title'),el.getAttribute('type')].join(' '));
      return /search|جستجو|جست.?و.?جو|find/.test(hint)||el.getAttribute('role')==='searchbox'||el.getAttribute('type')==='search';
    });
    if(candidates.length===1)input=candidates[0];
    else return {ok:false,reason:'search_input_not_unique',candidates:candidates.slice(0,8).map(x=>({tag:x.tagName,placeholder:x.getAttribute('placeholder'),aria:x.getAttribute('aria-label')})),current_identity:current};
  }
  const query=wantedUser?'@'+wantedUser:(wanted||wantedId);
  input.focus();
  if('value' in input){const setter=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input),'value')?.set;if(setter)setter.call(input,query);else input.value=query;}else input.textContent=query;
  input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));
  input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',code:'Enter',bubbles:true}));input.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',bubbles:true}));
  await new Promise(r=>setTimeout(r,1400));
  let results=[];
  if(searchResultSelector){
    try{results=[...document.querySelectorAll(searchResultSelector)].filter(visible);}catch{}
    const parts=String(searchResultSelector).split(',').map(x=>x.trim()).filter(Boolean);
    const isBroad=parts.length>0 && parts.every(x=>/^(?:a|button|li|\*|\[role=[\"']?(?:option|button)[\"']?\])$/i.test(x));
    if(isBroad) results=results.filter(el=>el.closest('.chatlist, [role="listbox"], [role="list"], .search-results, [data-testid*="search-results"], [data-peer-id], [data-username], [data-user], [class*="row-clickable"]'));
  } else {
    // Never scan every anchor/button on the page: message bodies and public
    // landing pages can contain arbitrary links that mention the target handle.
    const containers=[...document.querySelectorAll('.chatlist, [role="listbox"], [role="list"], .search-results, [data-testid*="search-results"]')].filter(visible);
    results=containers.flatMap(root=>[...root.querySelectorAll('a,button,[role="option"],[role="button"]')]).filter(visible);
  }
  const evidenceFor = el => {
    const nodes=[el,...el.querySelectorAll('[data-peer-id],[data-username],[data-user],[class*=\"username\"]')].slice(0,120);
    const ids=nodes.map(x=>String(x.getAttribute('data-peer-id')||'').trim()).filter(Boolean);
    const usernames=nodes.flatMap(x=>[x.getAttribute('data-username'),x.getAttribute('data-user'),(/username/i.test(String(x.className||''))?x.innerText||x.textContent:'')]).filter(Boolean).map(v=>clean(v).replace(/^@+/,''));
    const rowHref=el.matches('a[href]')?String(el.getAttribute('href')||''):'';
    const text=clean(el.innerText||el.textContent);
    const raw=(el.innerText||el.textContent||'').trim();
    const handleInText = !!wantedUser && String(raw).toLocaleLowerCase().split(/[\s,،;；()<>]+/).some(token=>token.replace(/^[\"'`]+|[\"'`.]+$/g,'').replace(/^@+/, '')===wantedUser);
    const usernameMatch=!!wantedUser && (usernames.some(v=>v===wantedUser) || urlContainsUsername(rowHref) || handleInText);
    return {ids,usernames,rowHref,text,raw,usernameMatch};
  };
  // Resolve selectors that point at a ripple, list container or nested label
  // to the actual clickable result row. A configured container can therefore
  // be used without clicking the <ul> itself.
  const normalizedResults=[...new Set(results.flatMap(el=>{
    const clickable='a,button,[role="option"],[role="button"],[class*="row-clickable"]';
    if(el.matches(clickable) || el.matches('[data-peer-id]')) return [el];
    const ancestor=el.closest(clickable);
    if(ancestor) return [ancestor];
    const descendants=[...el.querySelectorAll(clickable+', [data-peer-id]')].filter(visible);
    return descendants.length?descendants:[el];
  }))];
  const matches=normalizedResults.map(el=>({el,...evidenceFor(el)})).filter(x=>{
    if(wantedId && x.ids.includes(wantedId)) return true;
    if(wantedUser && x.usernameMatch) return true;
    return !wantedId && !wantedUser && wanted && (x.text===wanted || x.text.startsWith(wanted));
  });
  const unique=[...new Set(matches.map(x=>x.el))];
  const pool=unique.filter(el=>!unique.some(other=>other!==el&&el.contains(other)));
  if(pool.length!==1){
    const candidateSummary=matches.slice(0,10).map(x=>({text:x.raw.slice(0,180),ids:x.ids.slice(0,4),usernames:x.usernames.slice(0,4),href:x.rowHref,username_match:x.usernameMatch}));
    return {ok:false,reason:pool.length?'ambiguous_search_results':(wantedId||wantedUser?'channel_identity_result_not_found':'channel_result_not_found'),candidates:candidateSummary,current_identity:current};
  }
  const target=pool[0].closest('a,button,[role="option"],[role="button"]')||pool[0];
  target.click();
  await new Promise(r=>setTimeout(r,500));
  const after=await waitForCurrentIdentity(5000);
  const verifiedAfterOpen=after.verified || ((!wantedId && !wantedUser && !targetUrl) && after.title_verified);
  if(!verifiedAfterOpen){
    return {ok:false,reason:(wantedId||wantedUser||targetUrl)?'active_channel_identity_not_verified':'active_channel_not_verified',clicked_result:evidenceFor(pool[0]).raw.slice(0,180),active_title:after.active_title,active_ids:after.active_ids,current_page:location.origin+location.pathname};
  }
  return {ok:true,opened:true,identity_verified:true,identity_method:after.method||'unique_display_name_result',active_title:after.active_title,clicked_result:evidenceFor(pool[0]).raw.slice(0,180),active_ids:after.active_ids,active_message_count:after.active_message_count,active_conversation:after.active_conversation};
}'''

_MESSAGE_DISCOVERY_FUNCTION = r'''(config) => {
  const rootSelector = String(config?.root?.selector || '').trim();
  const fields = config?.fields || {};
  const textDef = fields.text || {};
  const textSelector = String(textDef.selector || '').trim();
  const visible = el => {
    if (!el || el.nodeType !== 1) return false;
    try {
      const style = getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) > 0.02 && !!el.getClientRects().length;
    } catch { return false; }
  };
  const classTokens = el => {
    const raw = typeof el?.className === 'string' ? el.className : (el?.getAttribute?.('class') || '');
    return String(raw).split(/\s+/).map(x => x.trim()).filter(Boolean).slice(0, 16);
  };
  const normalizedText = value => String(value || '').replace(/\u00a0/g, ' ').replace(/[\t\r\n ]+/g, ' ').trim();
  const nodeText = el => normalizedText(el?.innerText || el?.textContent || '');
  const safeQuery = (root, selector) => {
    if (!root || !selector) return null;
    try { return selector === ':root' ? root : root.querySelector(selector); } catch { return null; }
  };
  const readField = (root, def) => {
    if (!def?.selector) return '';
    const node = safeQuery(root, String(def.selector));
    if (!node) return '';
    const attr = String(def.attribute || 'textContent');
    if (attr === 'textContent') return normalizedText(node.textContent);
    if (attr === 'innerText') return nodeText(node);
    if (attr === 'outerHTML') return String(node.outerHTML || '').slice(0, 5000);
    return normalizedText(node.getAttribute(attr));
  };
  const ignoredNode = el => {
    if (!el) return true;
    const tag = String(el.tagName || '').toLowerCase();
    if (/^(script|style|noscript|svg|path|button|input|textarea|select|option|nav|header|footer|time|canvas|iframe)$/.test(tag)) return true;
    const tokens = classTokens(el).join(' ').toLowerCase();
    return /(reaction|reactions|avatar|profile-photo|profile_image|timestamp|message-time|message_date|views|view-count|read-state|delivery-state|toolbar|menu|context-menu|composer|reply-markup|keyboard|forwarded-from)/.test(tokens);
  };
  const bodyHint = el => {
    const tokens = classTokens(el).join(' ').toLowerCase();
    return /(message[-_]?text|translatable|text[-_]?content|content[-_]?text|post[-_]?text|bubble[-_]?text|message[-_]?body|post[-_]?body|tweet[-_]?text|comment[-_]?body)/.test(tokens)
      || el?.hasAttribute?.('data-message-text') || el?.hasAttribute?.('data-text');
  };
  const bestBody = root => {
    if (!root) return {node: null, text: ''};
    const explicit = textSelector ? safeQuery(root, textSelector) : null;
    const explicitText = explicit ? nodeText(explicit) : '';
    if (explicitText) return {node: explicit, text: explicitText, configured: true};
    const selectors = [
      '[data-message-text]', '[data-text]', '.translatable-message', '.message-text',
      '[class*="message-text" i]', '[class*="message_text" i]', '[class*="message-body" i]',
      '[class*="post-text" i]', '[class*="tweet-text" i]', '[class*="bubble-content" i]',
      'blockquote', 'p', '[dir]'
    ];
    const candidates = [];
    const seen = new Set();
    for (const selector of selectors) {
      let nodes = [];
      try { nodes = [...root.querySelectorAll(selector)].slice(0, 160); } catch {}
      for (const node of nodes) if (!seen.has(node)) { seen.add(node); candidates.push(node); }
    }
    // A bounded fallback handles applications whose CSS class names are generated.
    if (candidates.length < 2) {
      let nodes = [];
      try { nodes = [...root.querySelectorAll('p,span,div')].slice(0, 180); } catch {}
      for (const node of nodes) if (!seen.has(node)) { seen.add(node); candidates.push(node); }
    }
    let best = null;
    for (const node of candidates) {
      if (!visible(node) || ignoredNode(node)) continue;
      const text = nodeText(node);
      if (!text || text.length > 12000) continue;
      const tokens = classTokens(node).join(' ').toLowerCase();
      let score = 0;
      if (bodyHint(node)) score += 14;
      if (node.hasAttribute('data-message-text')) score += 8;
      if (/translatable|message[-_]?text|post[-_]?text|tweet[-_]?text/.test(tokens)) score += 7;
      if (/^(p|blockquote)$/.test(String(node.tagName || '').toLowerCase())) score += 3;
      if (node.children.length === 0) score += 2;
      if (text.length >= 20 && text.length <= 2500) score += 2;
      if (text.length > 5000) score -= 4;
      if (ignoredNode(node)) score -= 30;
      // Prefer the smallest semantic node rather than a wrapper containing sender,
      // timestamp, reactions and the actual post body all together.
      if (node.parentElement && root.contains(node.parentElement) && nodeText(node.parentElement) === text) score += 1;
      if (!best || score > best.score || (score === best.score && text.length < best.text.length)) best = {node, text, score};
    }
    if (best && best.score >= 1) return {node: best.node, text: best.text, configured: false};
    const ownText = nodeText(root);
    return {node: root, text: ownText.slice(0, 12000), configured: false};
  };
  const firstValue = (root, selectors, attrs) => {
    for (const selector of selectors) {
      let nodes = [];
      try { nodes = [...root.querySelectorAll(selector)].slice(0, 12); } catch {}
      for (const node of nodes) {
        if (!visible(node)) continue;
        for (const attr of attrs) {
          const value = node.getAttribute?.(attr);
          if (value && String(value).trim()) return String(value).trim();
        }
        const value = nodeText(node);
        if (value && value.length <= 180) return value;
      }
    }
    return '';
  };
  const inferMeta = root => {
    const id = root.getAttribute('data-message-id') || root.getAttribute('data-mid') || root.getAttribute('data-id') || root.getAttribute('data-post') || root.id || '';
    let timestamp = '';
    const timeSelectors = ['time[datetime]', '[datetime]', '[data-timestamp]', '[data-time]', '[class*="time-inner" i][title]', '[class*="timestamp" i]', '[class*="message-time" i]', '[class*="message_date" i]', '[class*="date" i][title]', 'time[title]', '[aria-label*="20"]'];
    for (const selector of timeSelectors) {
      let nodes = [];
      try { nodes = [...root.querySelectorAll(selector)].slice(0, 16); } catch {}
      for (const node of nodes) {
        for (const attr of ['datetime','data-timestamp','data-time','title','aria-label']) {
          const value = String(node.getAttribute?.(attr) || '').trim();
          if (value && dateLike(value)) { timestamp = value; break; }
        }
        if (!timestamp) { const value = nodeText(node); if (value && dateLike(value)) timestamp = value; }
        if (timestamp) break;
      }
      if (timestamp) break;
    }
    const sender = firstValue(root,
      ['[data-sender]', '[data-author]', '[class*="author" i]', '[class*="sender" i]', '[class*="username" i]', '[class*="peer-name" i]', '[class*="user-name" i]'],
      ['data-sender', 'data-author', 'aria-label', 'title']);
    return {id, timestamp, sender};
  };
  const recordFor = root => {
    if (!visible(root)) return null;
    const body = bestBody(root);
    if (!body.text) return null;
    const meta = inferMeta(root);
    return {el: root, body: body.node, text: body.text.slice(0, 14000), body_configured: !!body.configured, ...meta};
  };
  const chromePattern = /(chatlist|chat[-_]?list|navigation[-_]?item|folders[-_]?sidebar|menu[-_]?horizontal|toolbar|contacts?[-_]?list|peer[-_]?list|dialogs?[-_]?list|conversation[-_]?list|recent[-_]?chats?|search[-_]?results|folder[-_]?list)/i;
  const sidebarPattern = /(sidebar|side[-_]?nav|left[-_]?panel)/i;
  const chromeHint = el => {
    let node = el;
    for (let depth = 0; node && depth < 7; depth++, node = node.parentElement) {
      const value = `${node.id || ''} ${classTokens(node).join(' ')} ${node.getAttribute('role') || ''} ${node.getAttribute('aria-label') || ''} ${node.getAttribute('data-testid') || ''}`;
      if (chromePattern.test(value)) return true;
      if ((depth === 0 || node.tagName === 'ASIDE' || node.tagName === 'NAV' || node.getAttribute('role') === 'navigation') && sidebarPattern.test(value)) return true;
      if (node.tagName === 'ASIDE' || node.tagName === 'NAV' || node.getAttribute('role') === 'navigation') return true;
      if (node.tagName === 'MAIN' || node.getAttribute('role') === 'main') break;
    }
    return false;
  };
  const semanticRootTokens = tokens => tokens.filter(token =>
    /(?:^|[-_])(message|msg|bubble|post|tweet|comment|chat|entry|item|feed)(?:$|[-_])/i.test(token)
    && !/(text|body|content|author|sender|footer|header|meta|reaction|avatar|time|date|translat|preview|attachment|name|title)/i.test(token)
    && !chromePattern.test(token));
  const hasMessageHint = el => {
    if (chromeHint(el)) return false;
    const tokens = classTokens(el);
    const tag = String(el.tagName || '').toLowerCase();
    const explicitId = el.hasAttribute('data-message-id') || el.hasAttribute('data-mid') || el.hasAttribute('data-post');
    const explicitTest = /message|post|comment|tweet|bubble/i.test(el.getAttribute('data-testid') || '');
    if (/^(a|button|nav|header|footer)$/i.test(tag) && !explicitId && !explicitTest) return false;
    return semanticRootTokens(tokens).length > 0
      || /^(article|li)$/i.test(tag)
      || el.getAttribute('role') === 'article'
      || explicitTest || explicitId;
  };
  const groupSignature = el => {
    const tag = String(el.tagName || '').toLowerCase();
    const tokens = classTokens(el);
    const semantic = semanticRootTokens(tokens);
    const testid = String(el.getAttribute('data-testid') || '');
    if (testid && /message|post|comment|tweet|bubble/i.test(testid)) return `testid:${tag}:${testid.toLowerCase()}`;
    if (semantic.length) return `class:${tag}:${semantic.sort().slice(0, 4).join('.')}`;
    if (el.getAttribute('role') === 'article') return `role:${tag}:article`;
    if (/^(article|li)$/i.test(tag)) return `tag:${tag}`;
    if (el.hasAttribute('data-message-id') || el.hasAttribute('data-mid') || el.hasAttribute('data-post')) return `data:${tag}:message`;
    return '';
  };
  const selectorHint = (el, groupNodes) => {
    const tag = String(el.tagName || 'div').toLowerCase();
    const common = classTokens(el).filter(token => groupNodes.every(node => classTokens(node).includes(token)));
    const stable = common.filter(token => /message|msg|bubble|post|tweet|comment|chat|entry|item|feed/i.test(token));
    if (stable.length) return tag + stable.map(token => `.${token.replace(/[^a-zA-Z0-9_-]/g, '')}`).join('');
    if (el.getAttribute('role') === 'article') return '[role="article"]';
    if (el.getAttribute('data-testid')) return `[data-testid="${String(el.getAttribute('data-testid')).replace(/"/g, '')}"]`;
    if (/^(article|li)$/i.test(tag)) return tag;
    return '';
  };
  const contextHint = parent => {
    let node = parent;
    for (let depth = 0; node && depth < 7; depth++, node = node.parentElement) {
      const value = `${node.id || ''} ${classTokens(node).join(' ')} ${node.getAttribute('role') || ''}`.toLowerCase();
      if (chromePattern.test(value)) return false;
      if (node.tagName === 'MAIN' || node.getAttribute('role') === 'main') return true;
      if (/(conversation[-_]?view|active[-_]?chat|chat[-_]?history|message[-_]?list|message[-_]?history|timeline|feed[-_]?list|thread[-_]?view|channel[-_]?history|message[-_]?pane|chat[-_]?pane)/.test(value)) return true;
    }
    return false;
  };
  const dateLike = value => {
    const v = String(value || '').replace(/[۰-۹٠-٩]/g, ch => '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'.includes(ch) ? String('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩'.indexOf(ch) % 10) : ch);
    return /(?:^|[^\d])\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?=$|[T\s,])/.test(v)
      || /\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}\b/.test(v)
      || /\b[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}\b/.test(v)
      || /\d{1,2}\s+(فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور|مهر|آبان|آذر|دی|بهمن|اسفند)\s+1[2-4]\d{2}/.test(v)
      || /^[A-Za-z]{3},?\s+\d{1,2}\s+[A-Za-z]{3}\s+\d{4}/.test(v)
      || /^\d{10,13}$/.test(v.trim());
  };
  const scoreRecord = (record, parent) => {
    const el = record.el;
    const tokens = classTokens(el);
    const sem = semanticRootTokens(tokens);
    let score = 0;
    const evidence = [];
    if (chromeHint(el)) return {score: -100, evidence: ['navigation/sidebar context rejected']};
    if (sem.length) { score += 10; evidence.push('message-like class'); }
    if (el.hasAttribute('data-message-id') || el.hasAttribute('data-mid') || el.hasAttribute('data-post')) { score += 9; evidence.push('message ID attribute'); }
    if (el.getAttribute('role') === 'article') { score += 5; evidence.push('article role'); }
    if (/^(article|li)$/i.test(el.tagName || '')) { score += 3; evidence.push('article/list semantics'); }
    if (/message|post|comment|tweet|bubble/i.test(el.getAttribute('data-testid') || '')) { score += 6; evidence.push('message test identifier'); }
    if (record.timestamp && dateLike(record.timestamp)) { score += 4; evidence.push('date-like timestamp'); }
    if (record.sender) { score += 1; evidence.push('sender metadata'); }
    if (record.body && bodyHint(record.body)) { score += 5; evidence.push('semantic message body'); }
    if (record.text.length >= 25 && record.text.length < 4000) score += 2;
    if (record.text.length > 8000) score -= 5;
    if (/(translatable|message[-_]?text|post[-_]?text|tweet[-_]?text)/i.test(tokens.join(' '))) score -= 4;
    if (contextHint(parent)) { score += 5; evidence.push('main conversation surface'); }
    return {score, evidence};
  };
  const elements = [...document.querySelectorAll('body *')].slice(0, 9000);
  const elementIndex = new Map(elements.map((el, index) => [el, index]));
  const semanticGroups = new Map();
  for (const el of elements) {
    if (!visible(el) || !el.parentElement || !hasMessageHint(el)) continue;
    const signature = groupSignature(el);
    if (!signature) continue;
    const key = `${signature}|parent:${elementIndex.has(el.parentElement) ? elementIndex.get(el.parentElement) : 'outer'}`;
    const group = semanticGroups.get(key) || {parent: el.parentElement, nodes: [], signature};
    group.nodes.push(el);
    semanticGroups.set(key, group);
  }
  const candidates = [];
  const seenGroupRoots = new Set();
  const evaluateGroup = (group, generic = false) => {
    const roots = [];
    for (const node of group.nodes) {
      if (chromeHint(node)) continue;
      const record = recordFor(node);
      if (!record) continue;
      const scored = scoreRecord(record, group.parent);
      roots.push({...record, score: scored.score, evidence: scored.evidence});
    }
    if (roots.length < 2) return;
    const avg = roots.reduce((sum, root) => sum + root.score, 0) / roots.length;
    const timestamps = roots.filter(root => root.timestamp).length;
    const semantic = roots.filter(root => root.score >= 10).length;
    const contextual = contextHint(group.parent);
    const repeatedBonus = Math.min(4, roots.length - 2) * 0.7;
    const score = avg + repeatedBonus + (timestamps >= 2 ? 2 : 0) + (contextual ? 1 : 0) - (generic ? 1 : 0);
    const bodyHints = roots.filter(root => root.body && bodyHint(root.body)).length;
    const minimum = generic ? (roots.length >= 3 && (timestamps >= 2 || contextual || bodyHints >= 2) ? 6 : 8) : 7;
    if (score < minimum || (generic && semantic === 0 && timestamps < 2 && !contextual && bodyHints < 2)) return;
    const selector = selectorHint(roots[0].el, roots.map(root => root.el));
    const key = roots.map(root => root.el).join('|');
    if (seenGroupRoots.has(key)) return;
    seenGroupRoots.add(key);
    const evidence = [...new Set(roots.flatMap(root => root.evidence))];
    candidates.push({roots, selector: selector || null, count: roots.length, score: Math.round(score * 10) / 10,
      confidence: Math.max(0.25, Math.min(0.99, score / 22)), evidence, sample: roots[0].text.slice(0, 140),
      sample_timestamp: roots[0].timestamp || '', parent_context: (() => { const parts=[]; let node=group.parent; for(let depth=0;node&&depth<4;depth++,node=node.parentElement) parts.push(`${node.tagName?.toLowerCase()||''}${node.id?'#'+node.id:''}${classTokens(node).slice(0,3).map(x=>'.'+x).join('')}`); return parts.join(' <- '); })(),
      conversation_context: contextual, generic});
  };
  for (const group of semanticGroups.values()) evaluateGroup(group, false);
  // Structural fallback: many messengers use generated CSS module names. In that
  // case, identify repeated sibling blocks by tag/shape, but require stronger
  // repeated-content and conversation-context evidence before trusting them.
  {
    const genericGroups = new Map();
    const parentIndex = new Map();
    let index = 0;
    for (const el of elements) {
      if (!el.parentElement) continue;
      if (!parentIndex.has(el.parentElement)) parentIndex.set(el.parentElement, ++index);
      const tag = String(el.tagName || '').toLowerCase();
      if (!/^(div|li|article|section)$/.test(tag) || chromeHint(el)) continue;
      const parent = el.parentElement;
      const shape = [...el.children].slice(0,6).map(child => String(child.tagName || '').toLowerCase()).join(',') || 'leaf';
      const key = `${parentIndex.get(parent)}:${tag}:${shape}:${Math.min(5, el.children.length)}`;
      const group = genericGroups.get(key) || {parent, nodes: [], signature: `generic:${tag}:${shape}`};
      if (group.nodes.length < 60) group.nodes.push(el);
      genericGroups.set(key, group);
    }
    for (const group of genericGroups.values()) if (group.nodes.length >= 2) evaluateGroup(group, true);
  }
  candidates.sort((a, b) => b.score - a.score || b.count - a.count || (a.generic ? 1 : -1));
  let inferred = candidates[0] || null;
  // If the configured selector points to a single outer history wrapper, prefer
  // the repeated child messages that were discovered inside it.
  let configuredNodes = [];
  let configuredRawCount = 0;
  let selectorError = '';
  if (rootSelector) {
    try {
      const rawConfigured = [...document.querySelectorAll(rootSelector)].slice(0, 10000);
      configuredRawCount = rawConfigured.length;
      configuredNodes = rawConfigured.filter(node => !chromeHint(node));
    }
    catch (error) { selectorError = String(error?.message || error); }
  }
  const configuredRecords = configuredNodes.map(recordFor).filter(Boolean);
  let selected = null;
  let mode = '';
  if (configuredRecords.length >= 2 && !(configuredRecords.length === 1 && inferred?.roots?.length >= 2)) {
    selected = configuredRecords;
    mode = configuredRecords.some(x => !x.body_configured) ? 'configured_root_with_automatic_text' : 'configured_exact';
  } else if (inferred?.roots?.length >= 2) {
    selected = inferred.roots;
    mode = rootSelector ? 'universal_recovery' : 'universal_auto_discovery';
  } else if (configuredRecords.length === 1 && (inferred?.roots?.length || 0) < 2) {
    selected = configuredRecords;
    mode = 'configured_single_root';
  } else {
    selected = [];
    mode = selectorError ? 'invalid_selector_auto_discovery_failed' : 'no_confident_repeated_message_roots';
  }
  const diagnostics = {
    page_url: location.origin + location.pathname,
    page_title: String(document.title || '').slice(0, 160),
    configured_selector: rootSelector || null,
    configured_selector_error: selectorError || null,
    configured_match_count: configuredRawCount,
    configured_usable_match_count: configuredNodes.length,
    configured_nonempty_count: configuredRecords.length,
    scanned_element_count: elements.length,
    semantic_candidate_count: [...semanticGroups.values()].reduce((sum, group) => sum + group.nodes.length, 0),
    inferred_group_count: candidates.length,
    selected_mode: mode,
    selected_root_count: selected.length,
    timestamp_mapped_count: selected.filter(x => x.timestamp && dateLike(x.timestamp)).length,
    sender_mapped_count: selected.filter(x => x.sender).length,
    timestamp_samples: selected.slice(0, 5).map(x => String(x.timestamp || '').slice(0, 100)),
    candidate_groups: candidates.slice(0, 8).map(candidate => ({selector:candidate.selector,count:candidate.count,score:candidate.score,confidence:Math.round(candidate.confidence*100),evidence:candidate.evidence,sample:candidate.sample,sample_timestamp:candidate.sample_timestamp,parent_context:candidate.parent_context,conversation_context:candidate.conversation_context,generic:candidate.generic})),
    scroll_containers: elements.filter(el => visible(el) && el.clientHeight > 100 && el.clientWidth > 120 && el.scrollHeight > el.clientHeight + 60 && /(auto|scroll|overlay)/.test(`${getComputedStyle(el).overflowY} ${getComputedStyle(el).overflow}`))
      .slice(0, 12).map(el => ({tag:String(el.tagName||'').toLowerCase(),id:String(el.id||'').slice(0,80),classes:classTokens(el).slice(0,6),role:el.getAttribute('role')||'',client_height:el.clientHeight,scroll_height:el.scrollHeight,text_excerpt:nodeText(el).slice(0,100)}))
  };
  if (!selected.length || !candidates.length || (selected.length && candidates[0]?.evidence?.includes('navigation/sidebar context rejected'))) {
    const classCounts = new Map();
    const tagCounts = new Map();
    for (const el of elements) {
      if (!visible(el)) continue;
      const tag = String(el.tagName || '').toLowerCase();
      tagCounts.set(tag, (tagCounts.get(tag) || 0) + 1);
      const classes = semanticRootTokens(classTokens(el));
      for (const token of classes) classCounts.set(token, (classCounts.get(token) || 0) + 1);
    }
    diagnostics.visible_tag_counts = [...tagCounts.entries()].sort((a,b)=>b[1]-a[1]).slice(0,12).map(([tag,count])=>({tag,count}));
    diagnostics.message_class_counts = [...classCounts.entries()].sort((a,b)=>b[1]-a[1]).slice(0,20).map(([class_name,count])=>({class_name,count}));
    diagnostics.sample_nodes = elements.filter(el => visible(el) && !chromeHint(el) && /^(article|li|div|section)$/i.test(el.tagName || '') && nodeText(el).length >= 20 && nodeText(el).length <= 1500)
      .slice(0, 12).map(el => ({tag: String(el.tagName || '').toLowerCase(), classes: classTokens(el).slice(0,8), role: el.getAttribute('role') || '', testid: el.getAttribute('data-testid') || '', text_excerpt: nodeText(el).slice(0,140), timestamp_excerpt: inferMeta(el).timestamp.slice(0,100)}));
  }
  const candidatesOut = candidates.slice(0, 8).map(candidate => ({selector: candidate.selector, count: candidate.count, score: candidate.score, confidence: Math.round(candidate.confidence * 100), evidence: candidate.evidence, sample: candidate.sample, sample_timestamp:candidate.sample_timestamp, parent_context:candidate.parent_context, conversation_context:candidate.conversation_context, generic: candidate.generic}));
  return {
    roots: selected,
    selector: selected === inferred?.roots ? (inferred.selector || '(structurally inferred message blocks)') : rootSelector,
    mode,
    exact_count: configuredNodes.length,
    matched_count: selected.length,
    candidates: candidatesOut,
    diagnostics
  };
}'''


_CAPTURE_SCRIPT = r'''async ({config, maxMessages, strategy, requestedStrategy, autoNavigation, maxScrollCycles}) => {
  const resolveUniversalMessageRoots = __MESSAGE_DISCOVERY_FUNCTION__;
  const rootSelector = String(config.root?.selector || '').trim();
  const fields = config.fields || {};
  const nav = config.navigation || {};
  const textSelector = String(fields.text?.selector||'').trim();
  const read = (root, def) => {
    if (!def || !def.selector) return '';
    let node = null;
    try { node = def.selector === ':root' ? root : root.querySelector(def.selector); } catch { return ''; }
    if (!node) return '';
    const attr = def.attribute || 'textContent';
    if (attr === 'textContent') return String(node.textContent || '').trim();
    if (attr === 'innerText') return String(node.innerText || node.textContent || '').trim();
    if (attr === 'outerHTML') return String(node.outerHTML || '').slice(0,5000);
    return String(node.getAttribute(attr) || '').trim();
  };
  const hash = s => { let h=2166136261; for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);} return (h>>>0).toString(16); };
  const clamp = (v, lo, hi, fallback) => { const n=Number(v); return Number.isFinite(n)?Math.max(lo,Math.min(hi,n)):fallback; };
  let rootResolution = resolveUniversalMessageRoots(config);
  let lastRootResolveAt = performance.now();
  const getRoots = (force=false) => {
    if(force || performance.now()-lastRootResolveAt>300){rootResolution=resolveUniversalMessageRoots(config);lastRootResolveAt=performance.now();}
    return rootResolution.roots || [];
  };
  const candidateRoots = rootResolution.candidates || [];
  if(!getRoots().length){
    return {items:[],root_count:0,scroll_cycles:0,strategy,requested_strategy:requestedStrategy||strategy,auto_navigation:!!autoNavigation,
      root_selector_diagnostics:{configured:rootSelector||null,used:rootResolution.selector,mode:rootResolution.mode,exact_count:rootResolution.exact_count,matched_count:0},
      message_root_candidates:candidateRoots,message_discovery_diagnostics:rootResolution.diagnostics,
      dom_diagnostics:rootResolution.diagnostics?.sample_nodes?.length?rootResolution.diagnostics:null,
      warnings:[`No confident repeated message blocks were detected. The saved selector was ${rootSelector||'(empty)'}. Inspect the DOM discovery diagnostics before changing selectors.`]};
  }
  const found = new Map();
  const scan = () => {
    const roots=getRoots(true);
    for (const record of roots) {
      const root=record.el;
      const text=read(root,fields.text) || record.text || '';
      if (!text) continue;
      const sender=read(root,fields.sender) || record.sender || '';
      const timestamp=read(root,fields.timestamp) || record.timestamp || '';
      const id=read(root,fields.message_id) || record.id || '';
      const key=id ? `id:${id}` : `fp:${hash([sender,timestamp,text].join('|'))}`;
      const attachments=[];
      if (fields.attachment?.selector) { try { for (const node of root.querySelectorAll(fields.attachment.selector)) { const attr=fields.attachment.attribute||'href'; const val=(attr==='textContent'||attr==='innerText')?(attr==='innerText'?(node.innerText||node.textContent||''):(node.textContent||'')):node.getAttribute(attr); if(val)attachments.push(String(val).slice(0,1000)); if(attachments.length>=20)break; } } catch {} }
      if (!found.has(key)) found.set(key,{raw_text:text.slice(0,14000),source_ref:key,posted_at:timestamp||null,sender:sender||'',attachments});
      if(found.size>=maxMessages) break;
    }
    return roots.length;
  };
  const contentSignature = () => {
    const roots=getRoots();
    const sample=roots.length?[roots[0],roots[Math.floor(roots.length/2)],roots[roots.length-1]].map(x=>String(x.text||'').slice(0,180)).join('|'):'';
    return `${roots.length}:${sample}`;
  };
  const visibleScrollState = el => {const top=Number(el?.scrollTop||0),height=Number(el?.scrollHeight||0),client=Number(el?.clientHeight||0);const reverse=!!el&&(Number(el.scrollTop)<-1||getComputedStyle(el).flexDirection==='column-reverse');return {top:Math.round(top),height:Math.round(height),client:Math.round(client),minTop:Math.round(reverse?Math.min(0,client-height):0),maxTop:Math.round(reverse?0:Math.max(0,height-client)),flexDirection:reverse?'column-reverse':'normal'};};
  const scrollerResolution={configured_selector:nav.scroll_selector||null,configured_selector_status:nav.scroll_selector?'not_checked':'not_configured',selected_by:'',fallback_used:false};
  const findScroller = () => {
    const roots=getRoots();
    const pageRoot=document.scrollingElement||document.documentElement;
    const containsMessages=el=>roots.some(record=>el===record.el||el.contains(record.el));
    const isScrollable=el=>{
      if(!el||el.clientHeight<=100||el.clientWidth<=120||el.scrollHeight<=el.clientHeight+30)return false;
      const style=getComputedStyle(el);
      // Some single-page messengers use overflow:hidden while handling wheel
      // input themselves; scrollTop remains writable on these containers.
      return /(auto|scroll|overlay|hidden)/.test(`${style.overflowY} ${style.overflow}`);
    };
    if(nav.scroll_selector){
      let chosen=null;try{chosen=document.querySelector(nav.scroll_selector);}catch{}
      if(!chosen) scrollerResolution.configured_selector_status='not_found';
      else if(chosen!==pageRoot&&chosen!==document.documentElement&&chosen!==document.body&&!containsMessages(chosen)) scrollerResolution.configured_selector_status='does_not_contain_selected_messages';
      else if(!isScrollable(chosen)) scrollerResolution.configured_selector_status='not_scrollable';
      else {scrollerResolution.configured_selector_status='used';scrollerResolution.selected_by='configured_selector';return chosen;}
      scrollerResolution.fallback_used=true;
    }
    // Infer the active pane from ancestors shared by the selected message
    // blocks. This is independent of platform class names and survives stale
    // saved selectors when a messenger redesigns its DOM.
    const ancestorHits=new Map();
    for(const record of roots.slice(0,160)){
      let node=record.el,depth=0;
      while(node&&node!==document.body&&depth<16){ancestorHits.set(node,(ancestorHits.get(node)||0)+1);node=node.parentElement;depth++;}
    }
    const candidates=[...ancestorHits.entries()].map(([el,hits])=>{
      let depth=0,node=el;while(node&&depth<80){depth++;node=node.parentElement;}
      return {el,hits,depth,range:el.scrollHeight-el.clientHeight,scrollable:isScrollable(el)};
    }).filter(x=>x.scrollable);
    candidates.sort((a,b)=>b.hits-a.hits || b.depth-a.depth || b.range-a.range);
    if(candidates[0]?.el){scrollerResolution.selected_by='message_ancestor_inference';return candidates[0].el;}
    if(isScrollable(pageRoot)){scrollerResolution.selected_by='document_fallback';return pageRoot;}
    scrollerResolution.selected_by='none';
    return null;
  };
  const waitForPage = async (budgetMs, minWaitMs, stableMs) => {
    const started=performance.now(); let lastContentChange=started; let mutationCount=0; let previous=contentSignature(); let contentChanged=false;
    const observer=new MutationObserver(records=>{mutationCount+=records.length;});
    try { observer.observe(document.body||document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['aria-busy','aria-expanded','data-state','class']}); } catch {}
    try {
      while (performance.now()-started<budgetMs) {
        await new Promise(resolve=>setTimeout(resolve,80));
        const next=contentSignature();
        if(next!==previous){previous=next;lastContentChange=performance.now();contentChanged=true;}
        const elapsed=performance.now()-started;
        // Decorative/loading DOM mutations do not end the wait. If no mapped
        // message signature changes, consume the full adaptive budget; slow
        // platforms can begin fetching messages well after the scroll event.
        if(contentChanged && elapsed>=minWaitMs && performance.now()-lastContentChange>=stableMs) break;
      }
    } finally { observer.disconnect(); }
    return {waited_ms:Math.round(performance.now()-started),mutations:mutationCount,saw_change:contentChanged};
  };
  let rootCount=scan(), cycles=0, unchanged=0;
  if(!found.size){
    return {items:[],root_count:rootCount,scroll_cycles:0,strategy,requested_strategy:requestedStrategy||strategy,auto_navigation:!!autoNavigation,
      root_selector_diagnostics:{configured:rootSelector||null,used:rootResolution.selector,mode:rootResolution.mode,exact_count:rootResolution.exact_count,matched_count:rootResolution.matched_count},
      message_root_candidates:rootResolution.candidates||candidateRoots,message_discovery_diagnostics:rootResolution.diagnostics,
      dom_diagnostics:rootResolution.diagnostics?.sample_nodes?.length?rootResolution.diagnostics:null,
      warnings:[`Message containers were detected (${rootCount}), but no message text could be read. Check the configured text field or inspect the automatic DOM discovery diagnostics.`]};
  }
  const maxCycles=Math.max(1,Math.min(500,Number(maxScrollCycles)||Number(nav.max_scrolls)||30));
  const waitMode=nav.wait_mode==='fixed'?'fixed':'adaptive';
  const minWait=clamp(nav.min_wait_ms,100,5000,250);
  const maxWait=clamp(nav.max_wait_ms,minWait,15000,8000);
  const stableMs=clamp(nav.stable_ms,50,2500,350);
  const fixedWait=clamp(nav.wait_ms,100,15000,1200);
  let adaptiveWait=clamp(fixedWait,minWait,maxWait,1200);
  const stepRatio=clamp(nav.scroll_step_ratio,0.2,1.5,0.78);
  const stepPx=clamp(nav.scroll_amount_px,0,10000,0);
  const maxIdle=Math.round(clamp(nav.max_idle_cycles,1,20,6));
  const diagnostics=[];
  const navigationWarnings=[];
  let scrollerName=''; let edgeIdleCycles=0; let olderEdgeConfirmed=false; let newerEdgeConfirmed=false;
  if(strategy!=='manual') {
    while(cycles<maxCycles && found.size<maxMessages && unchanged<maxIdle) {
      const before=found.size;
      const beforeSig=contentSignature();
      let scroller=null; let beforeScroll=null;
      if(strategy==='load_more' || strategy==='pagination') {
        if(!nav.button_selector) throw new Error('Set the button/next-page selector for this navigation strategy.');
        let button=null; try { button=document.querySelector(nav.button_selector); } catch {}
        if(!button || button.disabled || button.getAttribute('aria-disabled')==='true') break;
        button.click(); scrollerName='configured load-more/pagination control';
      } else {
        scroller=findScroller();
        if(!scroller){navigationWarnings.push('No scrollable ancestor containing the selected message blocks was found. The collector captured only the currently loaded messages; no unrelated page pane was scrolled.');break;}
        scrollerName=scroller===document.scrollingElement||scroller===document.documentElement||scroller===document.body?'document':`${scroller.tagName.toLowerCase()}${scroller.id?'#'+scroller.id:''}${typeof scroller.className==='string'&&scroller.className.trim()?'.'+scroller.className.trim().split(/\s+/).slice(0,2).join('.') : ''}`;
        const direction=nav.direction==='down'?1:-1;
        beforeScroll=visibleScrollState(scroller);
        if(cycles===0 && nav.direction!=='down' && Number(beforeScroll.top)>=Number(beforeScroll.maxTop)-4) newerEdgeConfirmed=true;
        if(cycles===0 && nav.direction==='down' && Number(beforeScroll.top)<=Number(beforeScroll.minTop)+4) olderEdgeConfirmed=true;
        const amount=stepPx>0?stepPx:Math.max(180,(scroller.clientHeight||window.innerHeight)*stepRatio);
        if(scroller===document.scrollingElement||scroller===document.documentElement||scroller===document.body) window.scrollBy({top:direction*amount,behavior:'instant'});
        else scroller.scrollBy({top:direction*amount,behavior:'instant'});
      }
      const budget=waitMode==='fixed'?fixedWait:adaptiveWait;
      const wait=await waitForPage(budget,Math.min(minWait,budget),stableMs);
      rootCount=scan(); cycles++;
      unchanged=found.size===before?unchanged+1:0;
      if(waitMode==='adaptive') adaptiveWait=found.size>before?Math.max(minWait,Math.round(adaptiveWait*0.78)):Math.min(maxWait,Math.round(adaptiveWait*1.45));
      let afterState={}; try { afterState=visibleScrollState(scroller||document.scrollingElement); } catch {}
      const contentChanged=contentSignature()!==beforeSig;
      const moved=(!beforeScroll ? (contentChanged || found.size>before) : (Math.abs(Number(afterState.top||0)-Number(beforeScroll.top||0))>1 || Number(afterState.height||0)!==Number(beforeScroll.height||0) || contentChanged || found.size>before));
      const olderEdge=Number(afterState.top||0)<=Number(afterState.minTop||0)+4;
      const newerEdge=Number(afterState.top||0)>=Number(afterState.maxTop||0)-4;
      edgeIdleCycles=moved?0:edgeIdleCycles+1;
      if(edgeIdleCycles>=2 && olderEdge) olderEdgeConfirmed=true;
      if(edgeIdleCycles>=2 && newerEdge) newerEdgeConfirmed=true;
      diagnostics.push({cycle:cycles,new_messages:found.size-before,waited_ms:wait.waited_ms,dom_mutations:wait.mutations,scroll:afterState,scroll_moved:moved,older_edge:olderEdge,newer_edge:newerEdge,content_changed:contentChanged});
      if(diagnostics.length>20) diagnostics.shift();
    }
  }
  return {items:[...found.values()].slice(0,maxMessages),root_count:rootCount,scroll_cycles:cycles,strategy,requested_strategy:requestedStrategy||strategy,auto_navigation:!!autoNavigation,stopped_after_no_new:unchanged>=maxIdle,
    root_selector_diagnostics:{configured:rootSelector||null,used:rootResolution.selector,mode:rootResolution.mode,exact_count:rootResolution.exact_count,matched_count:rootResolution.matched_count},
    message_root_candidates:rootResolution.candidates||candidateRoots,message_discovery_diagnostics:rootResolution.diagnostics,
    scroll_diagnostics:{mode:waitMode,scroller:scrollerName,scroller_resolution:scrollerResolution,step_ratio:stepRatio,min_wait_ms:minWait,max_wait_ms:maxWait,final_adaptive_wait_ms:adaptiveWait,max_idle_cycles:maxIdle,observed_movement:diagnostics.some(x=>x.scroll_moved),older_edge_confirmed:olderEdgeConfirmed,newer_edge_confirmed:newerEdgeConfirmed,edge_idle_cycles:edgeIdleCycles,last_cycles:diagnostics},warnings:navigationWarnings};
}'''


_SCAN_PAGE_SCRIPT = r'''({config, maxMessages}) => {
  const resolveUniversalMessageRoots = __MESSAGE_DISCOVERY_FUNCTION__;
  const discovery = resolveUniversalMessageRoots(config);
  const roots = discovery.roots || [];
  const fields = config.fields || {};
  const read = (root, def) => {
    if (!def || !def.selector) return '';
    let node = null;
    try { node = def.selector === ':root' ? root : root.querySelector(def.selector); } catch { return ''; }
    if (!node) return '';
    const attr = def.attribute || 'textContent';
    if (attr === 'textContent') return String(node.textContent || '').trim();
    if (attr === 'innerText') return String(node.innerText || node.textContent || '').trim();
    if (attr === 'outerHTML') return String(node.outerHTML || '').slice(0,5000);
    return String(node.getAttribute(attr) || '').trim();
  };
  const hash = s => { let h=2166136261; for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);} return (h>>>0).toString(16); };
  const items = [];
  for (const record of roots.slice(0, Math.max(1, Math.min(10000, Number(maxMessages)||10000)))) {
    const root = record.el;
    const text = read(root, fields.text) || record.text || '';
    if (!text) continue;
    const sender = read(root, fields.sender) || record.sender || '';
    const timestamp = read(root, fields.timestamp) || record.timestamp || '';
    const id = read(root, fields.message_id) || record.id || '';
    const key = id ? `id:${id}` : `fp:${hash([sender,timestamp,text].join('|'))}`;
    const attachments = [];
    if (fields.attachment?.selector) {
      try {
        for (const node of root.querySelectorAll(fields.attachment.selector)) {
          const attr = fields.attachment.attribute || 'href';
          const val = (attr==='textContent'||attr==='innerText') ? (attr==='innerText' ? (node.innerText||node.textContent||'') : (node.textContent||'')) : node.getAttribute(attr);
          if (val) attachments.push(String(val).slice(0,1000));
          if (attachments.length>=20) break;
        }
      } catch {}
    }
    items.push({raw_text:text.slice(0,14000),source_ref:key,posted_at:timestamp||null,sender:sender||'',attachments});
  }
  const nav = config.navigation || {};
  const previousSelector = nav.previous_page_selector || (config.site_preset === 'eitaa' ? 'a.js-messages_more[data-before]' : '');
  const nextSelector = nav.next_page_selector || (config.site_preset === 'eitaa' ? 'a.js-messages_more[data-after]' : '');
  let before = null, after = null;
  try { if (previousSelector) before = document.querySelector(previousSelector); } catch {}
  try { if (nextSelector) after = document.querySelector(nextSelector); } catch {}
  const dates = items.map(x => String(x.posted_at||'').slice(0,10)).filter(x => /^\d{4}-\d{2}-\d{2}$/.test(x)).sort();
  return {
    items,
    root_count: roots.length,
    root_selector_diagnostics: {configured:config.root?.selector||null,used:discovery.selector,mode:discovery.mode,exact_count:discovery.exact_count,matched_count:roots.length},
    message_root_candidates: discovery.candidates || [],
    message_discovery_diagnostics: discovery.diagnostics,
    dom_diagnostics: !roots.length ? discovery.diagnostics : null,
    before_href: before ? before.href : null,
    after_href: after ? after.href : null,
    oldest_date: dates[0] || null,
    newest_date: dates[dates.length-1] || null,
    page_url: location.href
  };
}'''

_SCAN_PAGE_SCRIPT = _SCAN_PAGE_SCRIPT.replace('__MESSAGE_DISCOVERY_FUNCTION__', _MESSAGE_DISCOVERY_FUNCTION)
_CAPTURE_SCRIPT = _CAPTURE_SCRIPT.replace('__MESSAGE_DISCOVERY_FUNCTION__', _MESSAGE_DISCOVERY_FUNCTION)


_TARGET_ROUTE_TOKENS = {"app_origin", "app_url", "username", "platform_id", "name", "target_url"}


def safe_chromium_launch_args(effective_uid: int | None = None) -> list[str]:
    """Build safe Chromium arguments and refuse root execution.

    Chromium's --no-sandbox switch is deliberately never used by Agent Shadi.
    On Linux, running the collector as root would otherwise force that unsafe
    mode, so fail early with an actionable instruction instead.
    """
    uid = effective_uid
    if uid is None and hasattr(os, "geteuid"):
        uid = os.geteuid()
    if uid == 0:
        raise RuntimeError(
            "Agent Shadi's browser collector is running as root. Chromium would require "
            "--no-sandbox in this mode, which is intentionally disabled for security. "
            "Stop Agent Shadi and restart it from your normal desktop user account without sudo. "
            "In Terminal, check with: id -u (the result must not be 0)."
        )
    return ["--disable-dev-shm-usage"]


def resolve_channel_target_url(channel: dict[str, Any], app_url: str, site_preset: str = "") -> tuple[str, dict[str, str]]:
    """Resolve a connector's canonical source URL into its in-app conversation route.

    A route template is optional and platform-agnostic. Presets may provide a
    default template, while users can override it for any web application.
    Supported tokens: {app_origin}, {app_url}, {username}, {platform_id},
    {name}, and {target_url}.
    """
    channel = channel if isinstance(channel, dict) else {}
    direct_url = str(channel.get("target_url") or "").strip()
    template = str(channel.get("target_url_template") or "").strip()
    username = str(channel.get("username") or "").strip().lstrip("@")
    platform_id = str(channel.get("platform_id") or "").strip()
    name = str(channel.get("name") or "").strip()

    if not username and direct_url:
        try:
            parts = [part for part in urlsplit(direct_url).path.split("/") if part]
            if parts:
                username = parts[-1].lstrip("@")
        except Exception:
            pass

    preset = str(site_preset or "").strip().lower()
    original_app_url = str(app_url or "").strip()
    app_host = (urlsplit(original_app_url).hostname or "").lower()
    if not preset and (app_host == "eitaa.com" or app_host.endswith(".eitaa.com")):
        preset = "eitaa"

    # Backward compatibility for saved connectors whose Website URL still
    # points at the public Eitaa landing page. Resolve against the authenticated
    # web client, even if an old database row has not yet gone through migration.
    effective_app_url = original_app_url
    app_origin_source = "connector_url"
    if preset == "eitaa" and app_host in {"eitaa.com", "www.eitaa.com"}:
        effective_app_url = "https://web.eitaa.com/"
        app_origin_source = "eitaa_web_client_fallback"
    effective_app_host = (urlsplit(effective_app_url).hostname or "").lower()
    if not template and effective_app_host == "web.eitaa.com" and username:
        template = "{app_origin}/#@{username}"
        source = "site_preset_default"
    elif template:
        source = "configured_template"
    else:
        source = "direct_url"

    if not template:
        return direct_url, {"mode": "direct" if direct_url else "none", "source": source, "configured_url": direct_url, "resolved_url": direct_url, "application_url": effective_app_url, "application_url_source": app_origin_source}

    parsed_app = urlsplit(effective_app_url)
    if parsed_app.scheme not in {"http", "https"} or not parsed_app.hostname or parsed_app.username or parsed_app.password:
        raise ValueError("The connector website URL must be a safe HTTP(S) URL before an in-app route template can be used.")
    app_origin = f"{parsed_app.scheme}://{parsed_app.netloc}"
    values = {
        "app_origin": app_origin,
        "app_url": effective_app_url,
        "username": quote(username, safe="@._-"),
        "platform_id": quote(platform_id, safe="-_."),
        "name": quote(name, safe="-_."),
        "target_url": quote(direct_url, safe=":/?#[]@!$&'()*+,;=%-._~"),
    }
    used = re.findall(r"\{([a-z_]+)\}", template)
    unknown = sorted(set(used) - _TARGET_ROUTE_TOKENS)
    if unknown or "{" in re.sub(r"\{[a-z_]+\}", "", template) or "}" in re.sub(r"\{[a-z_]+\}", "", template):
        raise ValueError("Unknown token in target URL template. Supported tokens: " + ", ".join("{" + x + "}" for x in sorted(_TARGET_ROUTE_TOKENS)) + ".")
    missing = [token for token in used if not values.get(token)]
    if missing:
        raise ValueError("The target URL template needs values for: " + ", ".join("{" + x + "}" for x in sorted(set(missing))) + ".")
    resolved = re.sub(r"\{([a-z_]+)\}", lambda match: values[match.group(1)], template)
    parsed = urlsplit(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("The resolved in-app target URL must be a safe HTTP(S) URL without embedded credentials.")
    if len(resolved) > 2000:
        raise ValueError("The resolved in-app target URL exceeds 2,000 characters.")
    return resolved, {"mode": "template", "source": source, "template": template, "configured_url": direct_url, "resolved_url": resolved, "application_url": effective_app_url, "application_url_source": app_origin_source}


class WebInspectorManager:
    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def start(self, workflow_id: str, connector_id: str, url: str, profile_dir: Path,
              persist_session: bool = True) -> dict[str, Any]:
        with self._lock:
            existing = self._sessions.get(connector_id)
            if existing and existing.get("status") in {"starting", "ready"}:
                return self.public_state(connector_id)
            if persist_session:
                effective_profile = Path(profile_dir)
            else:
                effective_profile = Path(tempfile.mkdtemp(prefix="agent-shadi-web-session-"))
                try:
                    effective_profile.chmod(0o700)
                except OSError:
                    pass
            state = {
                "status": "starting", "selected": None, "selection_revision": 0, "error": None, "logs": [],
                "stop": threading.Event(), "commands": queue.Queue(), "page": None,
                "context": None, "started_at": time.time(), "profile_dir": str(effective_profile),
                "persist_session": bool(persist_session),
            }
            self._sessions[connector_id] = state
        thread = threading.Thread(target=self._worker, args=(workflow_id, connector_id, url, effective_profile, state), daemon=True, name=f"web-inspector-{connector_id}")
        state["thread"] = thread
        thread.start()
        return self.public_state(connector_id)

    @staticmethod
    def _localize_timestamp(value: Any, timezone_name: str = "Asia/Tehran") -> str | None:
        """Normalize a timestamp into the timezone configured for this connector.

        Naive timestamps are treated as UTC. The timezone is a per-connector
        setting, so the same collector can handle platforms using different
        timestamp conventions without platform-specific parsing branches.
        """
        raw = str(value or "").strip()
        if not raw:
            return None
        # Normalize Persian and Arabic-Indic digits before parsing. Messenger
        # clients frequently render timestamps as Jalali dates in the UI even
        # when the collector's range is normalized to Gregorian ISO days.
        normalized = raw.translate(str.maketrans({**{ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}, **{ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}}))
        try:
            channel_tz = ZoneInfo(str(timezone_name or "UTC"))
        except ZoneInfoNotFoundError:
            channel_tz = timezone.utc
        persian_months = {
            "فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4, "مرداد": 5, "شهریور": 6,
            "مهر": 7, "آبان": 8, "آذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12,
        }
        month_pattern = "|".join(sorted(persian_months, key=len, reverse=True))
        textual_jalali = re.search(rf"(?<!\d)(\d{{1,2}})\s+({month_pattern})\s+(1[2-4]\d{{2}})(?:[،, ]+(\d{{1,2}}):(\d{{2}})(?::(\d{{2}}))?)?", normalized)
        if textual_jalali:
            jd, month_name, jy = textual_jalali.group(1, 2, 3)
            try:
                gy, gm, gd = jalali_to_gregorian(int(jy), persian_months[month_name], int(jd))
                hour, minute, second = (int(textual_jalali.group(i) or 0) for i in (4, 5, 6))
                return datetime(gy, gm, gd, hour, minute, second, tzinfo=channel_tz).isoformat(timespec="seconds")
            except ValueError:
                return None
        jalali_match = re.search(r"(?<!\d)(1[2-4]\d{2})[./-](\d{1,2})[./-](\d{1,2})(?:[ T،,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", normalized)
        if jalali_match:
            jy, jm, jd = map(int, jalali_match.group(1, 2, 3))
            try:
                gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
                hour, minute, second = (int(jalali_match.group(i) or 0) for i in (4, 5, 6))
                parsed = datetime(gy, gm, gd, hour, minute, second)
                return parsed.replace(tzinfo=channel_tz).isoformat(timespec="seconds")
            except (ValueError, ZoneInfoNotFoundError):
                return None
        raw = normalized
        if re.fullmatch(r"\d{10}(?:\d{3})?", raw):
            try:
                epoch = int(raw) / (1000 if len(raw) == 13 else 1)
                return datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone(channel_tz).isoformat(timespec="seconds")
            except (ValueError, OverflowError, OSError):
                return None
        gregorian_slash = re.fullmatch(r"(19\d{2}|20\d{2}|21\d{2})[/.](\d{1,2})[/.](\d{1,2})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", raw)
        if gregorian_slash:
            try:
                year, month, day = map(int, gregorian_slash.group(1, 2, 3))
                hour, minute, second = (int(gregorian_slash.group(i) or 0) for i in (4, 5, 6))
                return datetime(year, month, day, hour, minute, second, tzinfo=channel_tz).isoformat(timespec="seconds")
            except ValueError:
                return None
        if len(raw) == 10 and raw[4:5] == "-" and raw[7:8] == "-":
            try:
                datetime.strptime(raw, "%Y-%m-%d")
                return raw
            except ValueError:
                return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            try:
                channel_tz = ZoneInfo(str(timezone_name or "UTC"))
            except ZoneInfoNotFoundError:
                channel_tz = timezone.utc
            return parsed.astimezone(channel_tz).isoformat(timespec="seconds")
        except (TypeError, ValueError, OverflowError):
            pass
        # Some web messaging clients expose a human-readable local timestamp
        # in title attributes rather than an ISO datetime. Interpret these
        # strings in the connector's configured timezone.
        try:
            channel_tz = ZoneInfo(str(timezone_name or "UTC"))
        except ZoneInfoNotFoundError:
            channel_tz = timezone.utc
        for fmt in ("%d %B %Y, %H:%M:%S", "%d %B %Y, %H:%M", "%B %d, %Y, %H:%M:%S", "%B %d, %Y, %H:%M"):
            try:
                parsed = datetime.strptime(raw, fmt).replace(tzinfo=channel_tz)
                return parsed.isoformat(timespec="seconds")
            except ValueError:
                continue
        try:
            parsed_rfc = parsedate_to_datetime(raw)
            if parsed_rfc:
                if parsed_rfc.tzinfo is None:
                    parsed_rfc = parsed_rfc.replace(tzinfo=timezone.utc)
                return parsed_rfc.astimezone(channel_tz).isoformat(timespec="seconds")
        except (TypeError, ValueError, OverflowError):
            pass
        return None

    @classmethod
    def _iso_day(cls, value: Any, timezone_name: str = "Asia/Tehran") -> str | None:
        raw = str(value or "").strip()
        localized = cls._localize_timestamp(raw, timezone_name)
        if localized:
            return localized[:10]
        if len(raw) == 10 and raw[4:5] == "-" and raw[7:8] == "-":
            try:
                time.strptime(raw, "%Y-%m-%d")
                return raw
            except ValueError:
                return None
        return None

    def _capture_scrolling_date_range(
        self, page: Any, args: dict[str, Any], *, initial_page: dict[str, Any] | None = None,
        reason: str = "Pagination controls are unavailable; using message-pane scrolling instead."
    ) -> dict[str, Any]:
        """Collect a date range by proving both history boundaries in a message pane.

        A SPA may open a conversation at an intermediate scroll position. In that
        case, scrolling only toward older messages can find the start boundary but
        cannot prove that the newest/end boundary was covered. We first move toward
        the configured newer direction, then reverse toward older history. Each
        browser evaluation performs one scroll step so the Python layer can merge
        deduplicated messages and apply timezone-aware date boundaries.
        """
        config = args.get("config") if isinstance(args.get("config"), dict) else {}
        nav = config.get("navigation") if isinstance(config.get("navigation"), dict) else {}
        start_day = str(args.get("dateStart") or "")
        end_day = str(args.get("dateEnd") or "")
        if not start_day or not end_day or start_day > end_day:
            raise RuntimeError("A valid start and end date are required for date-range scrolling.")
        timestamp_timezone = str(nav.get("timestamp_timezone") or ("Asia/Tehran" if config.get("site_preset") == "eitaa" else "UTC"))
        max_scrolls = max(1, min(500, int(nav.get("max_scrolls") or 30)))
        max_messages = max(1, min(10000, int(args.get("maxMessages") or 100)))
        page_limit = max(100, min(10000, max_messages * 2))
        max_idle = max(1, min(20, int(nav.get("max_idle_cycles") or 6)))
        older_direction = "down" if str(nav.get("direction") or "up") == "down" else "up"
        newer_direction = "up" if older_direction == "down" else "down"
        collected: dict[str, dict[str, Any]] = {}
        scanned_refs: set[str] = set()
        undated = excluded_before = excluded_after = 0
        oldest_seen: str | None = None
        newest_seen: str | None = None
        root_count = 0
        latest_result: dict[str, Any] = {}
        cycle_diagnostics: list[dict[str, Any]] = []
        warnings = [reason]
        older_edge_confirmed = False
        newer_edge_confirmed = False
        start_bound_confirmed = False
        end_bound_confirmed = False

        def merge_items(items: list[dict[str, Any]]) -> None:
            nonlocal undated, excluded_before, excluded_after, oldest_seen, newest_seen
            for original in items:
                message = dict(original)
                localized = self._localize_timestamp(message.get("posted_at"), timestamp_timezone)
                if localized:
                    message["posted_at"] = localized
                key = str(message.get("source_ref") or "")
                if not key:
                    key = "fp:" + str(hash((message.get("sender"), message.get("posted_at"), message.get("raw_text"))))
                if key in scanned_refs:
                    continue
                scanned_refs.add(key)
                day = self._iso_day(message.get("posted_at"), timestamp_timezone)
                if not day:
                    undated += 1
                    continue
                oldest_seen = min(oldest_seen, day) if oldest_seen else day
                newest_seen = max(newest_seen, day) if newest_seen else day
                if day < start_day:
                    excluded_before += 1
                elif day > end_day:
                    excluded_after += 1
                else:
                    collected.setdefault(key, message)

        if initial_page:
            root_count = int(initial_page.get("root_count") or 0)
            latest_result = initial_page
            merge_items(initial_page.get("items") or [])

        # A timestamp already outside either side of the requested interval is
        # sufficient proof for that boundary; otherwise inspect the physical edge.
        if newest_seen and newest_seen > end_day:
            end_bound_confirmed = True
        if oldest_seen and oldest_seen < start_day:
            start_bound_confirmed = True

        base_scroll_config = {**config, "navigation": {**nav, "strategy": "infinite_scroll"}}

        def run_phase(direction: str, phase: str) -> str:
            """Run one direction until its date/physical boundary is proven or it stalls."""
            nonlocal latest_result, root_count, older_edge_confirmed, newer_edge_confirmed
            phase_idle = 0
            for _ in range(max_scrolls):
                phase_config = {
                    **base_scroll_config,
                    "navigation": {**base_scroll_config.get("navigation", {}), "direction": direction},
                }
                payload = {
                    "config": phase_config,
                    "maxMessages": page_limit,
                    "strategy": "infinite_scroll",
                    "requestedStrategy": str(args.get("requestedStrategy") or nav.get("strategy") or "pagination"),
                    "autoNavigation": True,
                    "maxScrollCycles": 1,
                    "phase": phase,
                }
                try:
                    current = page.evaluate(_CAPTURE_SCRIPT, payload)
                except Exception as exc:
                    warnings.append(f"The {phase} message-pane scroll attempt failed: {str(exc)[:260]}")
                    return "scroll_execution_failed"

                latest_result = current or {}
                root_count = int(latest_result.get("root_count") or root_count)
                merge_items(latest_result.get("items") or [])
                scroll_diag = latest_result.get("scroll_diagnostics") or {}
                steps = scroll_diag.get("last_cycles") or []
                if not steps:
                    resolution = scroll_diag.get("scroller_resolution") or {}
                    if resolution.get("selected_by") == "none":
                        return "scroll_container_not_found"
                    phase_idle += 1
                    if phase_idle >= max_idle:
                        return f"{phase}_scroll_stalled"
                    continue

                cycle_info = dict(steps[-1])
                cycle_info["cycle"] = len(cycle_diagnostics) + 1
                cycle_info["phase"] = phase
                cycle_info["direction"] = direction
                cycle_diagnostics.append(cycle_info)
                if len(cycle_diagnostics) > 30:
                    cycle_diagnostics.pop(0)
                moved = bool(cycle_info.get("scroll_moved"))
                phase_idle = 0 if moved else phase_idle + 1

                if scroll_diag.get("newer_edge_confirmed"):
                    newer_edge_confirmed = True
                if scroll_diag.get("older_edge_confirmed"):
                    older_edge_confirmed = True
                if phase == "newer" and cycle_info.get("newer_edge"):
                    newer_edge_confirmed = True
                if phase == "older" and phase_idle >= 2 and cycle_info.get("older_edge"):
                    older_edge_confirmed = True

                warnings.extend(str(x) for x in (latest_result.get("warnings") or []) if str(x) not in warnings)

                if newest_seen and newest_seen > end_day:
                    end_bound_confirmed = True
                    return "end_boundary_crossed"
                if older_edge_confirmed:
                    return "older_history_exhausted"
                if phase == "newer" and newer_edge_confirmed:
                    return "newer_history_exhausted"
                if oldest_seen and oldest_seen < start_day:
                    return "start_boundary_crossed"
                if len(collected) >= max_messages:
                    return "max_messages_reached"

                resolution = scroll_diag.get("scroller_resolution") or {}
                if resolution.get("selected_by") == "none":
                    return "scroll_container_not_found"
                if phase_idle >= max_idle:
                    return f"{phase}_scroll_stalled"
            return f"{phase}_scroll_limit_reached"

        # First prove the newest side. If the visible messages are already newer
        # than the requested end date, no extra downward navigation is necessary.
        newer_stop_reason = "newer_boundary_already_crossed" if end_bound_confirmed else "not_needed"
        if not end_bound_confirmed:
            newer_stop_reason = run_phase(newer_direction, "newer")
            if newer_stop_reason == "max_messages_reached":
                start_bound_confirmed = bool(oldest_seen and oldest_seen < start_day)
            elif newer_stop_reason in {"scroll_container_not_found", "scroll_execution_failed"}:
                warnings.append("The newest history boundary could not be checked because the message-pane scroll container was unavailable.")
            elif newer_stop_reason.endswith("scroll_stalled") or newer_stop_reason.endswith("scroll_limit_reached"):
                warnings.append("The collector could not confirm the newest/end boundary before its navigation limit. The date range may be incomplete on the newer side.")

        # Then move toward older messages, unless the initial/newer pass already
        # exposed a message strictly before the requested start date.
        older_stop_reason = "start_boundary_already_crossed" if start_bound_confirmed or (oldest_seen and oldest_seen < start_day) else "not_needed"
        if not start_bound_confirmed and not (oldest_seen and oldest_seen < start_day) and len(collected) < max_messages:
            older_stop_reason = run_phase(older_direction, "older")
            if older_stop_reason == "start_boundary_crossed":
                start_bound_confirmed = True
            elif older_stop_reason == "older_history_exhausted":
                older_edge_confirmed = True
                start_bound_confirmed = True
            elif older_stop_reason == "max_messages_reached":
                pass
            elif older_stop_reason in {"scroll_container_not_found", "scroll_execution_failed"}:
                warnings.append("The older/start boundary could not be checked because the message-pane scroll container was unavailable.")
            elif older_stop_reason.endswith("scroll_stalled"):
                warnings.append("The message viewport stopped changing before the requested older-date boundary was reached.")
            elif older_stop_reason.endswith("scroll_limit_reached"):
                warnings.append(f"Reached the configured {max_scrolls}-step older-history limit before crossing the requested start date.")

        if oldest_seen and oldest_seen < start_day:
            start_bound_confirmed = True
        if newest_seen and newest_seen > end_day:
            end_bound_confirmed = True
        start_bound_confirmed = bool(start_bound_confirmed or older_edge_confirmed)
        end_bound_confirmed = bool(end_bound_confirmed or newer_edge_confirmed)
        if undated:
            warnings.append(f"Skipped {undated} message(s) without a parseable timestamp; they cannot be safely date-filtered.")
        if len(collected) >= max_messages:
            stop_reason = "max_messages_reached"
        elif start_bound_confirmed and end_bound_confirmed:
            stop_reason = "date_range_boundaries_verified"
        elif not end_bound_confirmed:
            stop_reason = "newer_boundary_not_reached"
        elif not start_bound_confirmed:
            stop_reason = "start_boundary_not_reached"
        else:
            stop_reason = older_stop_reason or newer_stop_reason

        complete = start_bound_confirmed and end_bound_confirmed and len(collected) < max_messages
        return {
            "items": list(collected.values())[:max_messages],
            "root_count": root_count,
            "scroll_cycles": len(cycle_diagnostics),
            "strategy": "infinite_scroll",
            "requested_strategy": str(args.get("requestedStrategy") or nav.get("strategy") or "pagination"),
            "auto_navigation": True,
            "stopped_after_no_new": newer_stop_reason.endswith("scroll_stalled") or older_stop_reason.endswith("scroll_stalled"),
            "root_selector_diagnostics": latest_result.get("root_selector_diagnostics") or (initial_page or {}).get("root_selector_diagnostics"),
            "message_root_candidates": latest_result.get("message_root_candidates") or (initial_page or {}).get("message_root_candidates", []),
            "message_discovery_diagnostics": latest_result.get("message_discovery_diagnostics") or (initial_page or {}).get("message_discovery_diagnostics"),
            "dom_diagnostics": latest_result.get("dom_diagnostics") or (initial_page or {}).get("dom_diagnostics"),
            "scroll_diagnostics": {
                **(latest_result.get("scroll_diagnostics") or {}),
                "mode": "bidirectional-boundary-scroll",
                "observed_movement": any(x.get("scroll_moved") for x in cycle_diagnostics),
                "older_edge_confirmed": older_edge_confirmed,
                "newer_edge_confirmed": newer_edge_confirmed,
                "fallback_from": "pagination",
                "fallback_reason": reason,
                "boundary_traversal": {
                    "newer_direction": newer_direction,
                    "newer_stop_reason": newer_stop_reason,
                    "older_direction": older_direction,
                    "older_stop_reason": older_stop_reason,
                    "max_steps_per_direction": max_scrolls,
                },
                "last_cycles": cycle_diagnostics,
            },
            "date_range": {
                "start": start_day, "end": end_day, "scanned": len(scanned_refs),
                "in_range": len(collected), "undated": undated,
                "excluded_before": excluded_before, "excluded_after": excluded_after,
                "oldest_seen": oldest_seen, "newest_seen": newest_seen,
                "start_bound_confirmed": start_bound_confirmed,
                "end_bound_confirmed": end_bound_confirmed,
                "complete": complete, "stop_reason": stop_reason,
            },
            "warnings": warnings,
        }

    def _capture_paginated(self, page: Any, args: dict[str, Any]) -> dict[str, Any]:
        # Capture date-bounded pages through same-origin older/newer links.

        # Browser navigation is performed only on the page-owning worker thread.
        config = args["config"]
        start_day = str(args.get("dateStart") or "")
        end_day = str(args.get("dateEnd") or "")
        if not start_day or not end_day or start_day > end_day:
            raise RuntimeError("A valid start and end date are required for date-range pagination.")
        nav = config.get("navigation") or {}
        # Many messenger web clients are single-page applications with a
        # scrollable/virtualized history rather than previous/next page URLs.
        # A stale pagination strategy must not silently capture only the first
        # viewport: fall back to the same universal message-aware scroll engine.
        if config.get("site_preset") != "eitaa" and not nav.get("previous_page_selector"):
            return self._capture_scrolling_date_range(
                page, args, reason="No previous-page selector is configured; using message-pane scrolling instead."
            )
        wait_ms = max(250, min(10000, int(nav.get("wait_ms") or 1200)))
        timestamp_timezone = str(nav.get("timestamp_timezone") or ("Asia/Tehran" if config.get("site_preset") == "eitaa" else "UTC"))
        max_pages = max(1, min(500, int(nav.get("max_scrolls") or 30)))
        max_messages = max(1, min(10000, int(args.get("maxMessages") or 100)))
        page_limit = max(100, min(10000, max_messages * 2))
        collected: dict[str, dict[str, Any]] = {}
        visited_urls: set[str] = set()
        page_turns = 0
        scanned_total = 0
        undated = 0
        excluded_before = 0
        excluded_after = 0
        oldest_seen: str | None = None
        newest_seen: str | None = None
        warnings: list[str] = []
        stop_reason = "date_range_covered"
        start_bound_confirmed = False
        end_bound_confirmed = False
        older_history_exhausted = False
        newer_history_exhausted = False

        def scan() -> dict[str, Any]:
            nonlocal scanned_total, undated, excluded_before, excluded_after, oldest_seen, newest_seen
            page_data = page.evaluate(_SCAN_PAGE_SCRIPT, {"config": config, "maxMessages": page_limit})
            items = page_data.get("items") or []
            scanned_total += len(items)
            page_days: list[str] = []
            for message in items:
                localized_timestamp = self._localize_timestamp(message.get("posted_at"), timestamp_timezone)
                if localized_timestamp:
                    message["posted_at"] = localized_timestamp
                day = self._iso_day(message.get("posted_at"), timestamp_timezone)
                if not day:
                    undated += 1
                    continue
                page_days.append(day)
                if day < start_day:
                    excluded_before += 1
                    continue
                if day > end_day:
                    excluded_after += 1
                    continue
                key = str(message.get("source_ref") or "")
                if not key:
                    key = "fp:" + str(hash((message.get("sender"), message.get("posted_at"), message.get("raw_text"))))
                collected.setdefault(key, message)
            if page_days:
                page_oldest, page_newest = min(page_days), max(page_days)
                oldest_seen = min(oldest_seen, page_oldest) if oldest_seen else page_oldest
                newest_seen = max(newest_seen, page_newest) if newest_seen else page_newest
            signature = tuple(sorted(str(x.get("source_ref") or "") for x in items if x.get("source_ref")))
            page_data["page_oldest"] = min(page_days) if page_days else None
            page_data["page_newest"] = max(page_days) if page_days else None
            page_data["signature"] = signature
            return page_data

        def goto_link(kind: str, page_data: dict[str, Any]) -> bool:
            nonlocal page_turns, stop_reason
            href = page_data.get("before_href" if kind == "older" else "after_href")
            if not href:
                stop_reason = "older_history_exhausted" if kind == "older" else "newer_history_exhausted"
                return False
            current_url = page.url
            target = urljoin(current_url, str(href))
            current_parts, target_parts = urlparse(current_url), urlparse(target)
            if (target_parts.scheme not in {"http", "https"}
                    or target_parts.scheme.lower() != current_parts.scheme.lower()
                    or target_parts.netloc.lower() != current_parts.netloc.lower()):
                warnings.append(f"Ignored a {kind} pagination link because it left the current website origin.")
                stop_reason = "unsafe_pagination_link"
                return False
            if target in visited_urls:
                stop_reason = "pagination_loop_detected"
                warnings.append(f"The {kind} pagination link led to a page already visited; stopped to prevent a loop.")
                return False
            if page_turns >= max_pages:
                stop_reason = "maximum_page_turns_reached"
                warnings.append(f"Stopped at the configured limit of {max_pages} pagination turns.")
                return False
            visited_urls.add(target)
            page.goto(target, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector("body", timeout=15000)
            except Exception:
                warnings.append("The next history page did not expose a document body before the navigation timeout.")
            page.wait_for_timeout(wait_ms)
            page_turns += 1
            return True

        visited_urls.add(page.url)
        current = scan()
        if current.get("items") and not current.get("before_href"):
            return self._capture_scrolling_date_range(
                page, args, initial_page=current,
                reason="No older-history pagination link exists on this active conversation. Switching to automatic upward scrolling of the message pane."
            )
        if not current.get("items"):
            return {
                "items": [], "root_count": current.get("root_count", 0), "scroll_cycles": 0, "strategy": "pagination",
                "root_selector_diagnostics": current.get("root_selector_diagnostics"),
                "message_root_candidates": current.get("message_root_candidates", []),
                "message_discovery_diagnostics": current.get("message_discovery_diagnostics"),
                "dom_diagnostics": current.get("dom_diagnostics"),
                "date_range": {"start": start_day, "end": end_day, "scanned": scanned_total, "in_range": 0, "undated": undated, "oldest_seen": oldest_seen, "newest_seen": newest_seen, "start_bound_confirmed": False, "end_bound_confirmed": False, "complete": False, "stop_reason": "no_message_roots"},
                "warnings": ["No confident repeated message blocks were detected on the active page. The automatic DOM discovery diagnostics are attached; no history links were followed because message boundaries could not be verified."]
            }

        # A date boundary is only proven after crossing strictly beyond it
        # (not merely seeing a post on that date), because one date can span
        # multiple paginated pages. Reaching the actual beginning/end of the
        # channel also proves that no more history exists on that side.
        if current.get("page_newest") and current["page_newest"] < start_day:
            start_bound_confirmed = True
            while newest_seen and newest_seen <= end_day and len(collected) < max_messages:
                if not goto_link("newer", current):
                    newer_history_exhausted = not bool(current.get("after_href"))
                    break
                previous_signature = current.get("signature")
                current = scan()
                if current.get("signature") == previous_signature:
                    warnings.append("The newer-page link loaded the same message set; stopped instead of looping.")
                    stop_reason = "no_newer_page_progress"
                    break
        else:
            # Move older until at least one message before the requested start
            # day is observed, ensuring all posts on the first day are included.
            while current.get("page_oldest") and current["page_oldest"] >= start_day and len(collected) < max_messages:
                if not goto_link("older", current):
                    older_history_exhausted = not bool(current.get("before_href"))
                    break
                previous_signature = current.get("signature")
                current = scan()
                if current.get("signature") == previous_signature:
                    warnings.append("The older-page link loaded the same message set; stopped instead of looping.")
                    stop_reason = "no_older_page_progress"
                    break
                if current.get("page_oldest") and current["page_oldest"] < start_day:
                    break
            # If the first page already contained posts newer than the end date,
            # all pages down to the start boundary have now been visited. If not,
            # walk newer until a post after the end day or history exhaustion.
            while newest_seen and newest_seen <= end_day and len(collected) < max_messages:
                if not goto_link("newer", current):
                    newer_history_exhausted = not bool(current.get("after_href"))
                    break
                previous_signature = current.get("signature")
                current = scan()
                if current.get("signature") == previous_signature:
                    warnings.append("The newer-page link loaded the same message set; stopped instead of looping.")
                    stop_reason = "no_newer_page_progress"
                    break

        if oldest_seen and oldest_seen < start_day:
            start_bound_confirmed = True
        if older_history_exhausted:
            start_bound_confirmed = True
        if newest_seen and newest_seen > end_day:
            end_bound_confirmed = True
        if newer_history_exhausted:
            end_bound_confirmed = True
        if len(collected) >= max_messages:
            stop_reason = "max_messages_reached"
        elif not start_bound_confirmed and stop_reason == "date_range_covered":
            stop_reason = "start_boundary_not_reached"
        elif not end_bound_confirmed and stop_reason == "date_range_covered":
            stop_reason = "end_boundary_not_reached"
        if undated:
            warnings.append(f"Skipped {undated} message(s) without a parseable ISO timestamp; they cannot be safely date-filtered.")
        return {
            "items": list(collected.values())[:max_messages],
            "root_count": current.get("root_count", 0),
            "scroll_cycles": page_turns,
            "strategy": "pagination",
            "stopped_after_no_new": False,
            "root_selector_diagnostics": current.get("root_selector_diagnostics"),
            "message_root_candidates": current.get("message_root_candidates", []),
            "message_discovery_diagnostics": current.get("message_discovery_diagnostics"),
            "date_range": {"start": start_day, "end": end_day, "scanned": scanned_total, "in_range": min(len(collected), max_messages), "undated": undated, "excluded_before": excluded_before, "excluded_after": excluded_after, "oldest_seen": oldest_seen, "newest_seen": newest_seen, "start_bound_confirmed": start_bound_confirmed, "end_bound_confirmed": end_bound_confirmed, "complete": start_bound_confirmed and end_bound_confirmed and len(collected) < max_messages, "stop_reason": stop_reason},
            "warnings": warnings,
        }

    def _worker(self, workflow_id: str, connector_id: str, url: str, profile_dir: Path, state: dict[str, Any]) -> None:
        context = None
        try:
            from playwright.sync_api import sync_playwright
            profile_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            with sync_playwright() as p:
                browser_args = safe_chromium_launch_args()
                context = launch_persistent_context(p.chromium, user_data_dir=str(profile_dir), headless=False, viewport={"width": 1440, "height": 950}, args=browser_args)
                page = context.pages[0] if context.pages else context.new_page()
                state["context"] = context
                state["page"] = page
                page.expose_binding("__structuraSelect", lambda source, payload: self._on_select(connector_id, payload))
                page.add_init_script(_INIT_SCRIPT)
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                with self._lock:
                    state["status"] = "ready"
                    state["logs"].append(
                        "Browser opened. Use Click select in the page toolbar, or right-click an element and choose Select this element. "
                        + ("This connector's browser profile is persistent and will be kept locally when the window closes." if state.get("persist_session") else "This is a temporary session; its profile will be deleted when the browser closes.")
                    )
                while not state["stop"].wait(0.2):
                    try:
                        command = state["commands"].get_nowait()
                    except queue.Empty:
                        command = None
                    if command:
                        try:
                            if page.is_closed():
                                raise RuntimeError("The inspected browser tab has been closed.")
                            if command.get("type") == "arm_selection":
                                target = str(command.get("target") or "element")
                                armed = page.evaluate("target => typeof window.__structuraSetSelectionMode === 'function' ? window.__structuraSetSelectionMode(target) : {ok:false,reason:'inspector_not_installed'}", target)
                                if not armed or not armed.get("ok"):
                                    raise RuntimeError("The visual selector is not installed on this page. Reload the inspected tab or restart the browser inspector.")
                                command["result"] = {"status": "armed", "target": target, "message": f"Click an element in the browser to map {target.replace('_',' ')}."}
                                continue
                            if command.get("type") in {"agent_observe", "agent_action"}:
                                from app.sources.browser_agent import observe_page, execute_action
                                if command.get("type") == "agent_observe":
                                    command["result"] = observe_page(page)
                                else:
                                    command["result"] = execute_action(page, command.get("action") or {})
                                continue
                            args = command["args"]
                            channel_name = str(args.get("channelName") or "").strip()
                            identity_args = {
                                "name": channel_name,
                                "targetUrl": args.get("targetUrl") or "",
                                "username": args.get("username") or "",
                                "platformId": args.get("platformId") or "",
                                "identitySelector": args.get("identitySelector") or "",
                                "identityAttribute": args.get("identityAttribute") or "data-peer-id",
                                "searchInputSelector": args.get("searchInputSelector") or "",
                                "searchResultSelector": args.get("searchResultSelector") or "",
                                "messageSelector": (args.get("config") or {}).get("root", {}).get("selector", ""),
                                "textSelector": ((args.get("config") or {}).get("fields") or {}).get("text", {}).get("selector", ""),
                            }
                            # Collection is page-scoped: the operator has already
                            # manually opened the intended channel/page in this browser.
                            # Never search for or navigate to a configured channel URL.
                            has_identity = False
                            opened = {"skipped": True, "reason": "operator_selected_active_page", "identity_verified": False}
                            if has_identity:
                                opened = page.evaluate(_OPEN_CHANNEL_SCRIPT, identity_args)
                                if opened.get("navigation_required"):
                                    target_url = str(args.get("targetUrl") or "")
                                    parsed_target = urlparse(target_url)
                                    if parsed_target.scheme not in {"http", "https"} or not parsed_target.hostname or parsed_target.username or parsed_target.password:
                                        raise RuntimeError("The configured direct channel URL is not a safe HTTP(S) URL.")
                                    page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                                    try:
                                        page.wait_for_load_state("networkidle", timeout=2500)
                                    except Exception:
                                        pass
                                    page.wait_for_timeout(700)
                                    identity_args["targetUrlNavigated"] = True
                                    opened = page.evaluate(_OPEN_CHANNEL_SCRIPT, identity_args)
                                if not opened.get("ok") or (not opened.get("identity_verified") and not opened.get("skipped")):
                                    identity_label = channel_name or str(args.get("username") or args.get("platformId") or args.get("targetUrl") or "configured target")
                                    raise RuntimeError("Could not resolve and verify channel/conversation '" + identity_label + "': " + str(opened))
                            if args.get("strategy") == "pagination" and args.get("dateStart") and args.get("dateEnd"):
                                result = self._capture_paginated(page, args)
                            else:
                                result = page.evaluate(_CAPTURE_SCRIPT, {**args, "requestedStrategy": args.get('requestedStrategy'), "autoNavigation": args.get('autoNavigation')})
                            result["channel_open"] = opened or {"skipped": True, "reason": "no_channel_identity", "identity_verified": False}
                            command["result"] = result
                        except Exception as exc:
                            command["error"] = str(exc)
                        finally:
                            command["done"].set()
                    try:
                        if page.is_closed():
                            state["status"] = "browser_closed"
                            break
                    except Exception:
                        break
                if context:
                    context.close()
        except Exception as exc:
            state["error"] = str(exc)
            state["status"] = "failed"
        finally:
            if context:
                try: context.close()
                except Exception: pass
            if state.get("status") in {"ready", "starting"}:
                state["status"] = "stopped"
            state["page"] = None
            state["context"] = None
            if not state.get("persist_session"):
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except Exception:
                    pass

    def _on_select(self, connector_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist a picked element and acknowledge the exact selection revision to the page."""
        with self._lock:
            state = self._sessions.get(connector_id)
            if not state or state.get("status") != "ready":
                return {"ok": False, "error": "The connector browser session is no longer ready."}
            state["selected"] = dict(payload)
            state["selected"]["selected_at"] = datetime.now(timezone.utc).isoformat()
            state["selection_revision"] = int(state.get("selection_revision", 0)) + 1
            revision = state["selection_revision"]
            state.setdefault("logs", []).append(f"Selected {payload.get('tag','element')} · {payload.get('selector','')}")
            state["logs"] = state["logs"][-50:]
            return {"ok": True, "selection_revision": revision, "selected_for": payload.get("selected_for", "element")}

    def arm_selection(self, connector_id: str, target: str) -> dict[str, Any]:
        """Arm the browser's visual selector for one guided connector field."""
        allowed = {"root", "text", "sender", "timestamp", "message_id", "attachment", "element"}
        target = str(target or "element").strip()
        if target not in allowed:
            raise ValueError("Unsupported selector-picking target.")
        with self._lock:
            state = self._sessions.get(connector_id)
            if not state or state.get("status") != "ready":
                raise RuntimeError("Open the connector browser and wait until it is Ready before picking an element.")
            state["selected"] = None
            before_revision = int(state.get("selection_revision", 0))
            done = threading.Event()
            command = {"type": "arm_selection", "target": target, "before_revision": before_revision, "done": done, "result": None, "error": None}
            state["commands"].put(command)
        if not done.wait(8):
            raise TimeoutError("The browser did not arm the visual selector in time.")
        if command.get("error"):
            raise RuntimeError(command["error"])
        result = command.get("result") or {"status": "armed", "target": target}
        result["selection_revision"] = before_revision
        return result

    def _agent_command(self, connector_id: str, command_type: str, action: dict[str, Any] | None = None, timeout: float = 25) -> dict[str, Any]:
        with self._lock:
            state = self._sessions.get(connector_id)
            if not state or state.get("status") != "ready":
                raise RuntimeError("Open the source browser and wait until it is Ready before using the browser agent.")
            done = threading.Event()
            command = {"type": command_type, "action": action or {}, "done": done, "result": None, "error": None}
            state["commands"].put(command)
        if not done.wait(timeout):
            raise TimeoutError("The browser agent did not receive a response from the browser worker in time.")
        if command.get("error"):
            raise RuntimeError(command["error"])
        return command.get("result") or {}

    def agent_observe(self, connector_id: str) -> dict[str, Any]:
        return self._agent_command(connector_id, "agent_observe")

    def agent_action(self, connector_id: str, action: dict[str, Any]) -> dict[str, Any]:
        return self._agent_command(connector_id, "agent_action", action, timeout=35)

    def status(self, connector_id: str, profile_dir: Path | None = None,
               persist_session: bool = True) -> dict[str, Any]:
        with self._lock:
            return self.public_state(connector_id, profile_dir, persist_session)

    def selection_html(self, connector_id: str) -> dict[str, Any]:
        """Return the last selected element's exact HTML only on explicit request."""
        with self._lock:
            state = self._sessions.get(connector_id)
            selected = (state or {}).get("selected") or {}
            html = str(selected.get("outer_html") or "")
            if not html:
                raise RuntimeError("Select an element in the browser first. Turn on Click select in the page toolbar or right-click an element and choose Select.")
            return {"outer_html": html[:30000], "selector": selected.get("selector", ""), "tag": selected.get("tag", "")}

    def public_state(self, connector_id: str, profile_dir: Path | None = None,
                     persist_session: bool = True) -> dict[str, Any]:
        state = self._sessions.get(connector_id) or {}
        selected = state.get("selected") or None
        if selected:
            selected = {key: selected.get(key) for key in ("selector", "relative_selector", "field_selector", "root_selector", "message_root_selector", "root_tag", "repeated_count", "repeated_siblings", "selected_for", "tag", "text", "attributes", "selected_at")}
        active = state.get("status") in {"starting", "ready"}
        is_persistent = bool(state.get("persist_session")) if active else bool(persist_session)
        if active and state.get("profile_dir"):
            configured_profile = Path(state["profile_dir"])
        elif is_persistent and profile_dir:
            configured_profile = Path(profile_dir)
        else:
            configured_profile = None
        profile_files = 0
        profile_bytes = 0
        def has_files(path: Path) -> bool:
            nonlocal profile_files, profile_bytes
            try:
                if path.is_file():
                    profile_files += 1
                    profile_bytes += path.stat().st_size
                    return True
                if not path.is_dir():
                    return False
                found = False
                # IndexedDB has one origin directory before its LevelDB files;
                # inspect at most two directory levels and never read file data.
                for child_index, child in enumerate(path.iterdir()):
                    if child_index >= 256:
                        break
                    candidates = [child] if child.is_file() else []
                    if child.is_dir():
                        candidates.extend(x for index, x in enumerate(child.iterdir()) if index < 256 and x.is_file())
                    for item in candidates:
                        found = True
                        profile_files += 1
                        try:
                            profile_bytes += item.stat().st_size
                        except OSError:
                            pass
                return found
            except OSError:
                return False
        cookies_database_present = bool(configured_profile and any(
            has_files(configured_profile / rel) for rel in ("Default/Network/Cookies", "Default/Cookies")
        ))
        local_storage_present = bool(configured_profile and has_files(configured_profile / "Default/Local Storage/leveldb"))
        indexed_db_present = bool(configured_profile and has_files(configured_profile / "Default/IndexedDB"))
        session_storage_present = bool(configured_profile and has_files(configured_profile / "Default/Session Storage"))
        service_worker_storage_present = bool(configured_profile and has_files(configured_profile / "Default/Service Worker/Database"))
        has_site_storage = any((cookies_database_present, local_storage_present, indexed_db_present, session_storage_present, service_worker_storage_present))
        return {
            "status": state.get("status", "idle"), "selected": selected,
            "selection_revision": int(state.get("selection_revision", 0)),
            "error": state.get("error"), "logs": list(state.get("logs", []))[-30:],
            "session": {
                "persistent": is_persistent,
                "profile_directory": str(configured_profile) if configured_profile else "",
                "profile_exists": bool(configured_profile and configured_profile.exists()),
                "profile_files": profile_files, "profile_bytes": profile_bytes,
                "cookies_database_present": cookies_database_present,
                "local_storage_present": local_storage_present,
                "indexed_db_present": indexed_db_present,
                "session_storage_present": session_storage_present,
                "service_worker_storage_present": service_worker_storage_present,
                "has_saved_site_data": has_site_storage,
                "application_uid": os.getuid() if hasattr(os, "getuid") else None,
                "application_effective_uid": os.geteuid() if hasattr(os, "geteuid") else None,
                "application_running_as_root": bool(hasattr(os, "geteuid") and os.geteuid() == 0),
                "note": "Profile metadata and process identity only; cookie values, credentials and page content are never returned. A profile or storage database does not prove that a website login is still valid.",
            },
        }

    def stop(self, connector_id: str) -> dict[str, Any]:
        with self._lock:
            state = self._sessions.get(connector_id)
            if not state:
                return {"status": "idle"}
            state["stop"].set()
        return {"status": "stopping"}

    @staticmethod
    def resolve_capture_strategy(config: dict[str, Any], strategy: str | None, start_date: str | None, end_date: str | None) -> tuple[str, str, bool]:
        nav = config.get("navigation") if isinstance(config.get("navigation"), dict) else {}
        requested = str(strategy or nav.get("strategy") or "manual")
        effective = requested
        auto_navigation = False
        if start_date and end_date and requested == "manual" and str(nav.get("date_range_mode") or "auto") == "auto":
            effective = "infinite_scroll"
            auto_navigation = True
        return requested, effective, auto_navigation

    def capture(self, connector_id: str, config: dict[str, Any], max_messages: int = 100, strategy: str | None = None, timeout: float = 150, start_date: str | None = None, end_date: str | None = None, app_url: str = "") -> dict[str, Any]:
        with self._lock:
            state = self._sessions.get(connector_id)
            if not state or state.get("status") != "ready":
                raise RuntimeError("Open the visual inspector and wait until its status is Ready before collecting.")
            # Playwright objects are thread-affine. Only inspect/use the page in
            # the browser worker thread; this API thread communicates by queue.
            done = threading.Event()
            channel_cfg = config.get("channel") if isinstance(config.get("channel"), dict) else {}
            requested_strategy, effective_strategy, auto_navigation = self.resolve_capture_strategy(config, strategy, start_date, end_date)
            resolved_target_url, target_url_resolution = resolve_channel_target_url(channel_cfg, app_url, str(config.get("site_preset") or ""))
            command = {"args": {"config": config, "manualSelection": True, "maxMessages": max(1, min(10000, int(max_messages))), "strategy": effective_strategy, "requestedStrategy": requested_strategy, "autoNavigation": auto_navigation, "dateStart": start_date, "dateEnd": end_date, "channelName": str(channel_cfg.get("name") or ""), "targetUrl": resolved_target_url, "targetUrlResolution": target_url_resolution, "username": str(channel_cfg.get("username") or ""), "platformId": str(channel_cfg.get("platform_id") or ""), "identitySelector": str(channel_cfg.get("identity_selector") or ""), "identityAttribute": str(channel_cfg.get("identity_attribute") or "data-peer-id"), "searchInputSelector": str(channel_cfg.get("search_input_selector") or ""), "searchResultSelector": str(channel_cfg.get("search_result_selector") or "")}, "done": done, "result": None, "error": None}
            state["commands"].put(command)
        if not done.wait(timeout):
            raise TimeoutError("The browser collection command timed out.")
        if command["error"]:
            raise RuntimeError(command["error"])
        result = command["result"] or {"items": [], "root_count": 0, "scroll_cycles": 0}
        result["target_url_resolution"] = target_url_resolution
        return result


web_inspector_manager = WebInspectorManager()
