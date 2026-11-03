// Older workers send tournament chips / 100. New workers identify native chip
// snapshots explicitly, so a mixed fleet never rescales those chips a second time.
export function liveDisplaySnapshot(payload){
 if(!payload.tournament||payload.amount_unit==='tournament_chips')return payload;
 const chips=value=>Math.round(Number(value||0)*100);
 return {...payload,pot:chips(payload.pot),big_blind:chips(payload.big_blind),
  seats:payload.seats.map(seat=>({...seat,stack:chips(seat.stack),bet:chips(seat.bet)})),
  result:payload.result?{...payload.result,winners:(payload.result.winners||[]).map(w=>({...w,amount:chips(w.amount)}))}:payload.result};
}

export function formatLiveAmount(value,tournament){
 return tournament?Number(value||0).toLocaleString(undefined,{maximumFractionDigits:0}):Number(value||0).toFixed(2);
}
