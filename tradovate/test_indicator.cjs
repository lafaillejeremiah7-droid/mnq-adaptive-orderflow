/* Native Tradovate chart tests; runs with Node, no Tradovate login or data. */
"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const code = fs.readFileSync(path.join(__dirname, "MNQPayoutSetupCoach.js"), "utf8");
function load() {
    const exports = {};
    const sandbox = {
        module: { exports },
        require: function (name) {
            if (name === "./tools/predef") return {
                styles: { solidLine: function () { return {}; } }
            };
            if (name === "./tools/meta") return {
                InputType: { BARS: "bars" }, AreaChoice: { NEW: "new" }
            };
            throw Error("Unexpected module " + name);
        }
    };
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox, {timeout: 5000});
    return sandbox.module.exports;
}
const indicator = load();
function mockBar(minute, opts) {
    opts = opts || {};
    const day = new Date(Date.parse("2026-11-12T14:30:00Z") + minute*60*1000);
    const price = opts.price ?? 20100;
    const bid = opts.bid ?? 3, ask = opts.ask ?? 5;
    const levels = [
        {price: price - .25, askVol: 1, bidVol: bid-1, vol: bid},
        {price: price, askVol: ask-1, bidVol: 1, vol: ask}
    ];
    return {
        timestamp: function () {return day;},
        open: function () {return price-.25;},
        high: function () {return price;},
        low: function () {return price-.25;},
        close: function () {return price;},
        bidVolume: function () {return bid;},
        offerVolume: function () {return ask;},
        profile: function () {return opts.noProfile ? null : levels;},
        isLast: function () {return Boolean(opts.isLast);}
    };
}
test("Indicator definition uses same Tradovate chart and volume profiles", function() {
    assert.equal(indicator.requirements.volumeProfiles, true);
    assert.equal(indicator.name, "MNQPayoutSetupCoach");
    assert.equal(typeof indicator.calculator, "function");
    assert.doesNotMatch(code, /fetch\s*\(|WebSocket\s*\(|XMLHttpRequest|chrome\.runtime|Authorization/);
});
test("No candidate until a complete RTH history exists", function () {
    const c = new indicator.calculator();
    c.contractInfo = {product:"MNQ"};
    c.init();
    assert.equal(c.map(mockBar(45,{isLast:true}),0),undefined);
    assert.equal(c.last.valid,false);
    assert.equal(c.last.reason,"INCOMPLETE_RTH_HISTORY");
});
test("Handles 70 minutes of Tradovate bars and excludes active bar", function () {
    const c = new indicator.calculator();
    c.contractInfo = {product:"MNQ"};
    c.init();
    for (let i=0;i<70;i++) {
        const result = c.map(mockBar(i,{isLast:i===69,price:20100 + Math.floor(i/15)*.25}),i);
        if (i===69) {
            assert.notEqual(result,undefined);
            assert.equal(result.value,0);
            assert.equal(c.last.valid,true);
            assert.equal(c.last.cvd,69*2);
        } else assert.equal(result,undefined);
    }
    const before = c.last.cvd;
    c.map(mockBar(69,{isLast:true,price:20100 + Math.floor(69/15)*.25}),69);
    assert.equal(c.last.cvd,before);
});
test("Absent volume profile is never converted to an invented signal", function () {
    const c = new indicator.calculator();
    c.contractInfo = {product:"MNQ"};
    c.init();
    assert.equal(c.map(mockBar(0,{isLast:true,noProfile:true}),0),undefined);
    assert.equal(c.bars.size,0);
});
test("Missing one-minute bar invalidates the output", function () {
    const c = new indicator.calculator();
    c.contractInfo = {product:"MNQ"};
    c.init();
    for (let i=0;i<=70;i++) {
        if(i===32)continue;
        c.map(mockBar(i,{isLast:i===70}),i);
    }
    assert.equal(c.last.valid,false);
    assert.equal(c.last.reason,"MISSING_RTH_MINUTES");
});
test("Refuses non-MNQ contracts",function(){
    const c=new indicator.calculator();
    c.contractInfo={product:"ES"};
    c.init();
    for(let i=0;i<=50;i++) c.map(mockBar(i,{isLast:i===50}),i);
    assert.equal(c.last.reason,"NOT_MNQ_CONTRACT");
});
test("Failed price-level volumes cannot become signals",function(){
    const c=new indicator.calculator();
    c.contractInfo={product:"MNQ"};
    c.init();
    const bar=mockBar(0,{isLast:true});
    bar.profile=function(){return [{price:20100,askVol:8,bidVol:9,vol:4}]};
    assert.equal(c.map(bar,0),undefined);
});
