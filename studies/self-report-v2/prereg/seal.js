#!/usr/bin/env node
// Seal: sha256(salt || file). Publish the hash, keep the salt secret until results.
const crypto = require('crypto'), fs = require('fs');
const file = process.argv[2] || __dirname + '/PREREG.md';
const salt = process.env.SEAL_SALT || crypto.randomBytes(32).toString('hex');
const h = crypto.createHash('sha256').update(salt).update(fs.readFileSync(file)).digest('hex');
if (!process.env.SEAL_SALT) console.error('NEW SALT (store privately, reveal with results):', salt);
console.log(h);
