// Compare generated HTTP arguments and callback effects without contacting a server.
const fs = require('fs');
const vm = require('vm');
const entries = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

function exercise(entry, lifted) {
    const log = { requests: [], outcomes: [], values: {}, error: null };
    const args = new Proxy({}, { get: (_, key) => 'value_' + String(key) });
    const context = {
        __args: args, step: { data: { values: args } }, __round: 1,
        __sbtPrefixPath: '/observed-prefix',
        pvg: {
            rtv: { get: key => log.values[key] || '{"A":{},"B":{},"config":{}}',
                   set: (key, value) => { log.values[key] = value; } },
            success: text => log.outcomes.push(['success', text]),
            fail: text => log.outcomes.push(['fail', text])
        }, svc: {}
    };
    for (const method of ['get', 'post', 'put', 'patch', 'delete']) {
        context.svc[method] = (url, options) => {
            log.requests.push({ method, url, headers: options.headers, body: options.body,
                parameters: options.parameters, expectedResponseCodes: options.expectedResponseCodes });
            if (options.callback) {
                options.callback({ code: options.expectedResponseCodes[0],
                    body: '{"id":"observed-id","name":"observed-name","config":{},"overlap":true,"A":200,"B":200}',
                    headers: { Location: '/observed/observed-id' } });
            }
        };
    }
    vm.createContext(context);
    try {
        if (lifted) vm.runInContext(entry.definition, context);
        vm.runInContext(lifted ? entry.story_call : entry.legacy_story, context);
    } catch (error) {
        log.error = error.name + ': ' + error.message;
    }
    log.prefixResult = vm.runInContext('typeof __sbtPrefixReadOk === "undefined" ? null : __sbtPrefixReadOk', context);
    return JSON.stringify(log);
}

for (const entry of entries) {
    const before = exercise(entry, false);
    const after = exercise(entry, true);
    const observed = JSON.parse(after);
    if (observed.error || observed.requests.length !== 1) {
        throw new Error('Incomplete stub execution for ' + entry.name + ': ' + observed.error);
    }
    if (before !== after) {
        throw new Error('Transport/callback behavior changed for ' + entry.name + ': ' + entry.operation);
    }
}
process.stdout.write('PASS: ' + entries.length + ' lifted request sites have identical HTTP arguments and callback effects in the Node stub.\n');
