// Worker snapshots use cash-table units (raw protocol amounts / 100).
// Tournament protocol amounts are chips; restore those units for display only.
export function liveDisplaySnapshot(payload){
 if(!payload.tournament)return payload;
 const chips=value=>Math.round(Number(value||0)*100);
 return {...payload,pot:chips(payload.pot),big_blind:chips(payload.big_blind),
  seats:payload.seats.map(seat=>({...seat,stack:chips(seat.stack),bet:chips(seat.bet)})),
  result:payload.result?{...payload.result,winners:(payload.result.winners||[]).map(w=>({...w,amount:chips(w.amount)}))}:payload.result};
}

export function formatLiveAmount(value,tournament){
 return tournament?Number(value||0).toLocaleString(undefined,{maximumFractionDigits:0}):Number(value||0).toFixed(2);
}
