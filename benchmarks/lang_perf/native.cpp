// C++20 NQ/MNQ trade aggregation experiment (not a live engine).
#include <algorithm>
#include <charconv>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
using i64=std::int64_t;
using i128=__int128_t;
static i64 integer(const std::string& text){
  i64 v=0;
  auto [ptr,error]=std::from_chars(text.data(),text.data()+text.size(),v);
  if(error!=std::errc{} || ptr!=text.data()+text.size())throw std::runtime_error("bad integer");
  return v;
}
static i128 abs128(i128 x){return x<0?-x:x;}
int main(int argc,char** argv) {
 try{
  if(argc!=2)throw std::runtime_error("provide one CSV path");
  std::ifstream f(argv[1]);
  if(!f)throw std::runtime_error("cannot open input");
  std::string line;
  if(!std::getline(f,line) || line!="timestamp_ns,price_ticks,size,side,sequence")
    throw std::runtime_error("bad header");
  std::unordered_map<i64,i64> vap;
  std::unordered_set<i64> minutes;
  i64 rows=0,total=0,weighted=0,buy=0,sell=0,unknown=0,checksum=0;
  i64 last_ts=-1,last_seq=-1;
  while(std::getline(f,line)){
    std::string fields[5];
    std::size_t start=0;
    for(int j=0;j<4;++j){
      auto sep=line.find(',',start);
      if(sep==std::string::npos)throw std::runtime_error("missing column");
      fields[j]=line.substr(start,sep-start);start=sep+1;
    }
    fields[4]=line.substr(start);
    if(fields[4].find(',')!=std::string::npos)throw std::runtime_error("extra column");
    i64 ts=integer(fields[0]),px=integer(fields[1]),qty=integer(fields[2]),seq=integer(fields[4]);
    if(ts<=0||px<=0||qty<=0||seq<0||
       (fields[3]!="B"&&fields[3]!="A"&&fields[3]!="N")||
       ts<last_ts||(ts==last_ts&&seq<=last_seq))throw std::runtime_error("invalid row/order");
    last_ts=ts;last_seq=seq;
    ++rows;total+=qty;weighted+=px*qty;vap[px]+=qty;
    i64 minute=ts/60000000000LL;minutes.insert(minute);
    if(fields[3]=="B"){buy+=qty;checksum+=minute*qty;}
    else if(fields[3]=="A"){sell+=qty;checksum-=minute*qty;}
    else unknown+=qty;
  }
  if(!rows)throw std::runtime_error("empty input");
  i64 lower=std::numeric_limits<i64>::max(),upper=0,poc=0,peak=-1;
  i128 closest=-1;
  for(auto [p,v]:vap){
    lower=std::min(lower,p);upper=std::max(upper,p);
    i128 d=abs128((i128)p*total-weighted);
    if(v>peak||(v==peak&&(closest<0||d<closest||(d==closest&&p<poc)))){
      peak=v;closest=d;poc=p;
    }
  }
  i64 lo=poc,hi=poc,covered=vap.at(poc),target=(total*7+9)/10;
  auto vol=[&](i64 p)->i64{auto it=vap.find(p);return it==vap.end()?0:it->second;};
  while(covered<target){
    bool has_l=lo>lower,has_r=hi<upper;
    if(!has_l&&!has_r)break;
    i64 choice;
    if(!has_l)choice=hi+1;
    else if(!has_r)choice=lo-1;
    else{
      i64 lv=vol(lo-1),rv=vol(hi+1);
      i128 ld=abs128((i128)(lo-1)*total-weighted);
      i128 rd=abs128((i128)(hi+1)*total-weighted);
      choice=(lv>rv||(lv==rv&&ld<=rd))?lo-1:hi+1;
    }
    covered+=vol(choice);lo=std::min(lo,choice);hi=std::max(hi,choice);
  }
  std::cout<<"{\"rows\":"<<rows<<",\"contracts\":"<<total
     <<",\"weighted_price_ticks\":"<<weighted<<",\"poc_ticks\":"<<poc
     <<",\"vah_ticks\":"<<hi<<",\"val_ticks\":"<<lo
     <<",\"buy_contracts\":"<<buy<<",\"sell_contracts\":"<<sell
     <<",\"unknown_contracts\":"<<unknown<<",\"unique_prices\":"<<vap.size()
     <<",\"unique_minutes\":"<<minutes.size()
     <<",\"minute_delta_weighted_checksum\":"<<checksum<<"}\n";
  return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 2;}
}
