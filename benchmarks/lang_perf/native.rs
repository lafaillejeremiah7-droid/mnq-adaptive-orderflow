// Rust stdlib-only NQ/MNQ trade aggregation experiment (not a live engine).
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{BufRead, BufReader};

fn run(path:&str)->Result<(),String> {
  let mut lines=BufReader::new(File::open(path).map_err(|e|e.to_string())?).lines();
  if lines.next().ok_or("empty file")?.map_err(|e|e.to_string())?
    != "timestamp_ns,price_ticks,size,side,sequence" {return Err("bad header".into());}
  let mut vap:HashMap<i64,i64>=HashMap::new();
  let mut minutes:HashSet<i64>=HashSet::new();
  let (mut rows,mut total,mut weighted,mut buy,mut sell,mut unknown,mut checksum):
    (i64,i64,i64,i64,i64,i64,i64)=(0,0,0,0,0,0,0);
  let mut previous:Option<(i64,i64)>=None;
  for line in lines {
    let line=line.map_err(|e|e.to_string())?;
    let parts:Vec<&str>=line.split(',').collect();
    if parts.len()!=5 {return Err("wrong column count".into());}
    let ts:i64=parts[0].parse().map_err(|_|"bad timestamp")?;
    let px:i64=parts[1].parse().map_err(|_|"bad price")?;
    let qty:i64=parts[2].parse().map_err(|_|"bad size")?;
    let seq:i64=parts[4].parse().map_err(|_|"bad sequence")?;
    if ts<=0 || px<=0 || qty<=0 || seq<0 ||
      (parts[3]!="B"&&parts[3]!="A"&&parts[3]!="N") ||
      previous.is_some_and(|old|(ts,seq)<=old) {return Err("bad trade or order".into());}
    previous=Some((ts,seq));
    rows+=1;total+=qty;weighted+=px*qty;
    *vap.entry(px).or_insert(0)+=qty;
    let minute=ts/60_000_000_000_i64;
    minutes.insert(minute);
    match parts[3] {
      "B"=>{buy+=qty;checksum+=minute*qty;},
      "A"=>{sell+=qty;checksum-=minute*qty;},
      _=>{unknown+=qty;}
    }
  }
  if rows==0 {return Err("empty dataset".into());}
  let (mut lower,mut upper)=(i64::MAX,i64::MIN);
  let (mut peak,mut poc,mut closest)=(-1_i64,0_i64,i128::MAX);
  for (&price,&volume) in &vap {
    lower=lower.min(price);upper=upper.max(price);
    let dist=((price as i128)*(total as i128)-(weighted as i128)).abs();
    if volume>peak || (volume==peak && (dist<closest || (dist==closest && price<poc))) {
      peak=volume;poc=price;closest=dist;
    }
  }
  let (mut lo,mut hi)=(poc,poc);
  let mut covered=*vap.get(&poc).ok_or("missing POC")?;
  let target=(total*7+9)/10;
  while covered<target {
    let (has_l,has_r)=(lo>lower,hi<upper);
    if !has_l && !has_r {break;}
    let choice=if !has_l {hi+1} else if !has_r {lo-1} else {
      let lv=*vap.get(&(lo-1)).unwrap_or(&0);
      let rv=*vap.get(&(hi+1)).unwrap_or(&0);
      let ld=(((lo-1) as i128)*(total as i128)-(weighted as i128)).abs();
      let rd=(((hi+1) as i128)*(total as i128)-(weighted as i128)).abs();
      if lv>rv || (lv==rv && ld<=rd) {lo-1} else {hi+1}
    };
    covered+=vap.get(&choice).copied().unwrap_or(0);
    lo=lo.min(choice);hi=hi.max(choice);
  }
  println!("{{\"rows\":{},\"contracts\":{},\"weighted_price_ticks\":{},\"poc_ticks\":{},\"vah_ticks\":{},\"val_ticks\":{},\"buy_contracts\":{},\"sell_contracts\":{},\"unknown_contracts\":{},\"unique_prices\":{},\"unique_minutes\":{},\"minute_delta_weighted_checksum\":{}}}",
    rows,total,weighted,poc,hi,lo,buy,sell,unknown,vap.len(),minutes.len(),checksum);
  Ok(())
}
fn main() {
  let args:Vec<String>=std::env::args().collect();
  if args.len()!=2 {eprintln!("expected one CSV path");std::process::exit(2);}
  if let Err(err)=run(&args[1]) {eprintln!("{}",err);std::process::exit(2);}
}
