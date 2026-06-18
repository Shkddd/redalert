// ============================================================
// 红色警戒 网页版 v2 — 完整 RTS 实现（优化版）
// ============================================================

const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const W = 800, H = 600;
const TILE = 40;
const MAP_COLS = 60;
const MAP_ROWS = 40;

// ---- 相机 ----
let camX = 0, camY = 0;
const CAM_SPEED = 6;

// ---- 资源 ----
let credits = 10000;
let oreStored = 0;
let power = 50;
let maxPower = 50;

// ---- 游戏对象 ----
let buildings = [];
let units = [];
let projectiles = [];
let particles = [];
let oreDeposits = [];
let gameTick = 0;
let gameOver = false;
let enemySpawnTimer = 0;

// ---- 选择 ----
let selectedUnits = [];
let selectedBuilding = null;
let isPlacing = null;
let mouseWorldX = 0, mouseWorldY = 0;
let mouseScreenX = 0, mouseScreenY = 0;
let isMouseDown = false;
let mouseOnCanvas = false;
// 框选
let isDragging = false;
let dragStartWorldX = 0, dragStartWorldY = 0;
let dragEndWorldX = 0, dragEndWorldY = 0;

// ---- 键盘 ----
const keys = {};

// ---- 地图地形 ----
let terrainMap = [];

// ---- 离屏缓存 ----
let terrainCache = null;
let minimapTerrainCache = null;

// ============================================================
// 二叉堆 (用于 A* 寻路优化)
// ============================================================
class BinaryHeap {
  constructor(scoreFn) {
    this.content = [];
    this.scoreFn = scoreFn;
  }

  push(element) {
    this.content.push(element);
    this._sinkDown(this.content.length - 1);
  }

  pop() {
    const result = this.content[0];
    const end = this.content.pop();
    if (this.content.length > 0) {
      this.content[0] = end;
      this._bubbleUp(0);
    }
    return result;
  }

  get size() { return this.content.length; }

  _sinkDown(n) {
    const element = this.content[n];
    const score = this.scoreFn(element);
    while (n > 0) {
      const parentN = ((n + 1) >> 1) - 1;
      const parent = this.content[parentN];
      if (score >= this.scoreFn(parent)) break;
      this.content[parentN] = element;
      this.content[n] = parent;
      n = parentN;
    }
  }

  _bubbleUp(n) {
    const length = this.content.length;
    const element = this.content[n];
    const score = this.scoreFn(element);
    while (true) {
      const child2N = (n + 1) << 1;
      const child1N = child2N - 1;
      let swap = null, child1Score;
      if (child1N < length) {
        child1Score = this.scoreFn(this.content[child1N]);
        if (child1Score < score) swap = child1N;
      }
      if (child2N < length) {
        const child2Score = this.scoreFn(this.content[child2N]);
        if (child2Score < (swap === null ? score : child1Score)) swap = child2N;
      }
      if (swap === null) break;
      this.content[n] = this.content[swap];
      this.content[swap] = element;
      n = swap;
    }
  }
}

// ============================================================
// 建筑配置
// ============================================================
const BUILDING_DEFS = {
  construction_yard: { name: '建造厂', hp: 1000, w: 3, h: 3, cost: 0, power: 0, color: '#4488cc', icon: '🏛' },
  power_plant: { name: '发电厂', hp: 400, w: 2, h: 2, cost: 800, power: 20, color: '#ffcc00', icon: '⚡' },
  ore_refinery: { name: '矿石精炼厂', hp: 600, w: 3, h: 2, cost: 2000, power: -10, color: '#88cc44', icon: '🏭' },
  barracks: { name: '兵营', hp: 500, w: 2, h: 2, cost: 1000, power: -5, color: '#44aa44', icon: '🎖' },
  war_factory: { name: '战车工厂', hp: 600, w: 3, h: 2, cost: 2000, power: -10, color: '#aa8844', icon: '⚙' },
  turret: { name: '炮塔', hp: 300, w: 1, h: 1, cost: 1500, power: -5, color: '#cc4444', icon: '🔫', range: 150, damage: 25 },
};

// ---- 单位配置 ----
const UNIT_DEFS = {
  rifle: { name: '步兵', hp: 80, speed: 1.2, damage: 8, range: 80, cost: 200, color: '#66cc66', size: 6, rof: 30, buildTime: 60, canSwim: false },
  tank: { name: '坦克', hp: 300, speed: 0.9, damage: 30, range: 100, cost: 800, color: '#cc8844', size: 10, rof: 40, buildTime: 120, canSwim: false },
  jeep: { name: '吉普车', hp: 150, speed: 1.8, damage: 12, range: 90, cost: 500, color: '#88ccff', size: 8, rof: 25, buildTime: 90, canSwim: false },
  mining_truck: { name: '矿车', hp: 200, speed: 1.2, damage: 5, range: 40, cost: 1200, color: '#ccaa44', size: 10, rof: 60, buildTime: 150, canSwim: false },
  repair_vehicle: { name: '修理车', hp: 180, speed: 1.4, damage: 3, range: 30, cost: 1000, color: '#44ccaa', size: 9, rof: 60, buildTime: 130, canSwim: false, repairRate: 2, repairRange: 60 },
};

const ENEMY_DEFS = {
  infantry: { name: '敌军步兵', hp: 60, speed: 1.0, damage: 6, range: 70, color: '#ff6666', size: 6, rof: 35 },
  enemy_tank: { name: '敌军坦克', hp: 250, speed: 0.8, damage: 25, range: 95, color: '#ff4444', size: 10, rof: 45 },
  enemy_jeep: { name: '敌军吉普', hp: 120, speed: 1.6, damage: 10, range: 85, color: '#ff8888', size: 8, rof: 30 },
};

// ============================================================
// 地图生成
// ============================================================
function generateTerrain() {
  terrainMap = [];
  for (let y = 0; y < MAP_ROWS; y++) {
    terrainMap[y] = [];
    for (let x = 0; x < MAP_COLS; x++) {
      terrainMap[y][x] = 0;
    }
  }

  const lakes = [
    { cx: 15, cy: 8, r: 4 },
    { cx: 35, cy: 12, r: 5 },
    { cx: 45, cy: 28, r: 6 },
    { cx: 8, cy: 30, r: 3 },
    { cx: 25, cy: 22, r: 4 },
    { cx: 50, cy: 8, r: 3 },
    { cx: 42, cy: 35, r: 4 },
  ];

  for (const lake of lakes) {
    for (let y = lake.cy - lake.r - 1; y <= lake.cy + lake.r + 1; y++) {
      for (let x = lake.cx - lake.r - 1; x <= lake.cx + lake.r + 1; x++) {
        if (x < 0 || x >= MAP_COLS || y < 0 || y >= MAP_ROWS) continue;
        const dist = Math.sqrt((x - lake.cx) ** 2 + (y - lake.cy) ** 2);
        if (dist < lake.r) {
          terrainMap[y][x] = 1;
        } else if (dist < lake.r + 1.5 && Math.random() < 0.4) {
          terrainMap[y][x] = 1;
        }
      }
    }
  }

  // 确保玩家出生点附近是陆地
  for (let y = 4; y < 14; y++) {
    for (let x = 2; x < 12; x++) {
      terrainMap[y][x] = 0;
    }
  }

  // 预渲染地形到离屏 canvas
  cacheTerrain();
  cacheMinimapTerrain();
}

function isWater(tx, ty) {
  if (tx < 0 || tx >= MAP_COLS || ty < 0 || ty >= MAP_ROWS) return true;
  return terrainMap[ty][tx] === 1;
}

function isWalkable(tx, ty, canSwim = false) {
  if (tx < 0 || tx >= MAP_COLS || ty < 0 || ty >= MAP_ROWS) return false;
  if (terrainMap[ty][tx] === 1) return canSwim;
  const wx = tx * TILE + TILE / 2, wy = ty * TILE + TILE / 2;
  for (const b of buildings) {
    if (!b.alive) continue;
    if (wx >= b.x - b.w * TILE / 2 && wx < b.x + b.w * TILE / 2 &&
        wy >= b.y - b.h * TILE / 2 && wy < b.y + b.h * TILE / 2) {
      return false;
    }
  }
  return true;
}

// ---- 地形离屏缓存 ----
function cacheTerrain() {
  terrainCache = document.createElement('canvas');
  terrainCache.width = MAP_COLS * TILE;
  terrainCache.height = MAP_ROWS * TILE;
  const tc = terrainCache.getContext('2d');

  for (let y = 0; y < MAP_ROWS; y++) {
    for (let x = 0; x < MAP_COLS; x++) {
      const sx = x * TILE, sy = y * TILE;
      if (terrainMap[y][x] === 1) {
        tc.fillStyle = (x + y) % 2 === 0 ? '#1a4a6a' : '#1d4d6d';
        tc.fillRect(sx, sy, TILE, TILE);
      } else {
        tc.fillStyle = (x + y) % 2 === 0 ? '#3a6a3a' : '#3d6d3d';
        tc.fillRect(sx, sy, TILE, TILE);
        // 随机植被
        if (Math.sin(x * 7.3 + y * 5.1) > 0.85) {
          tc.fillStyle = 'rgba(50,120,50,0.3)';
          tc.fillRect(sx + 8, sy + 10, 3, 6);
          tc.fillRect(sx + 14, sy + 12, 3, 4);
        }
      }
      tc.strokeStyle = 'rgba(0,0,0,0.06)';
      tc.strokeRect(sx, sy, TILE, TILE);
    }
  }
}

// ---- 小地图地形离屏缓存 ----
const minimapCanvas = document.getElementById('minimap');
const minimapCtx = minimapCanvas.getContext('2d');

function cacheMinimapTerrain() {
  minimapTerrainCache = document.createElement('canvas');
  minimapTerrainCache.width = minimapCanvas.width;
  minimapTerrainCache.height = minimapCanvas.height;
  const mc = minimapTerrainCache.getContext('2d');
  const scaleX = minimapCanvas.width / (MAP_COLS * TILE);
  const scaleY = minimapCanvas.height / (MAP_ROWS * TILE);

  mc.fillStyle = '#0a0a15';
  mc.fillRect(0, 0, minimapCanvas.width, minimapCanvas.height);

  for (let y = 0; y < MAP_ROWS; y++) {
    for (let x = 0; x < MAP_COLS; x++) {
      if (terrainMap[y][x] === 1) {
        mc.fillStyle = '#1a3a5a';
        mc.fillRect(x * scaleX * TILE, y * scaleY * TILE, Math.ceil(scaleX * TILE) + 1, Math.ceil(scaleY * TILE) + 1);
      }
    }
  }
}

// ---- 矿石生成 ----
function generateOre() {
  oreDeposits = [];
  for (let i = 0; i < 30; i++) {
    let x, y;
    let attempts = 0;
    do {
      x = 5 + Math.floor(Math.random() * (MAP_COLS - 10));
      y = 3 + Math.floor(Math.random() * (MAP_ROWS - 6));
      attempts++;
    } while ((isWater(x, y) || isNearStart(x, y)) && attempts < 50);

    if (!isWater(x, y)) {
      oreDeposits.push({
        x: x * TILE + TILE / 2,
        y: y * TILE + TILE / 2,
        amount: 500 + Math.floor(Math.random() * 1500),
        maxAmount: 2000,
        size: 8 + Math.random() * 6,
      });
    }
  }
}

function isNearStart(tx, ty) {
  return tx < 15 && ty < 15;
}

// ============================================================
// A* 寻路（二叉堆优化版）
// ============================================================
function heuristic(ax, ay, bx, by) {
  return Math.abs(ax - bx) + Math.abs(ay - by);
}

function findPath(fromX, fromY, toX, toY, canSwim = false) {
  const startTx = Math.floor(fromX / TILE);
  const startTy = Math.floor(fromY / TILE);
  const endTx = Math.floor(toX / TILE);
  const endTy = Math.floor(toY / TILE);

  if (!isWalkable(endTx, endTy, canSwim) && !(endTx === startTx && endTy === startTy)) {
    let best = null, bestDist = Infinity;
    for (let dy = -3; dy <= 3; dy++) {
      for (let dx = -3; dx <= 3; dx++) {
        const nx = endTx + dx, ny = endTy + dy;
        if (isWalkable(nx, ny, canSwim)) {
          const d = Math.abs(dx) + Math.abs(dy);
          if (d < bestDist) { bestDist = d; best = { tx: nx, ty: ny }; }
        }
      }
    }
    if (!best) return [];
    return findPath(fromX, fromY, best.tx * TILE + TILE / 2, best.ty * TILE + TILE / 2, canSwim);
  }

  const key = (tx, ty) => tx + ',' + ty;
  const openHeap = new BinaryHeap(n => n.f);
  const startNode = { tx: startTx, ty: startTy, g: 0, f: heuristic(startTx, startTy, endTx, endTy), parent: null };
  openHeap.push(startNode);
  const closed = new Set();

  const maxSteps = 500;
  let steps = 0;

  while (openHeap.size > 0 && steps < maxSteps) {
    steps++;
    const current = openHeap.pop();
    const ck = key(current.tx, current.ty);

    if (current.tx === endTx && current.ty === endTy) {
      const path = [];
      let node = current;
      while (node) {
        path.unshift({ x: node.tx * TILE + TILE / 2, y: node.ty * TILE + TILE / 2 });
        node = node.parent;
      }
      return path;
    }

    if (closed.has(ck)) continue;
    closed.add(ck);

    const dirs = [[0, -1], [0, 1], [-1, 0], [1, 0], [-1, -1], [-1, 1], [1, -1], [1, 1]];
    for (const [dx, dy] of dirs) {
      const nx = current.tx + dx, ny = current.ty + dy;
      const nk = key(nx, ny);
      if (closed.has(nk)) continue;
      if (!isWalkable(nx, ny, canSwim)) continue;

      const isDiag = dx !== 0 && dy !== 0;
      const moveCost = isDiag ? 1.414 : 1;
      const g = current.g + moveCost;
      const h = heuristic(nx, ny, endTx, endTy);
      openHeap.push({ tx: nx, ty: ny, g, f: g + h, parent: current });
    }
  }

  return [];
}

// ============================================================
// 建筑类
// ============================================================
class Building {
  constructor(type, tileX, tileY, owner = 'player') {
    const d = BUILDING_DEFS[type];
    this.type = type;
    this.name = d.name;
    this.tileX = tileX;
    this.tileY = tileY;
    this.w = d.w;
    this.h = d.h;
    this.x = tileX * TILE + d.w * TILE / 2;
    this.y = tileY * TILE + d.h * TILE / 2;
    this.hp = d.hp;
    this.maxHp = d.hp;
    this.color = d.color;
    this.range = d.range || 0;
    this.damage = d.damage || 0;
    this.cooldown = 0;
    this.owner = owner;
    this.buildAnim = 0;
    this.alive = true;
    this.icon = d.icon || '🏗';
  }

  update() {
    if (this.buildAnim < 1) this.buildAnim += 0.02;
    if (this.cooldown > 0) this.cooldown--;

    if (this.type === 'turret' && this.alive) {
      const target = findNearestEnemy(this.x, this.y, this.range);
      if (target && this.cooldown <= 0) {
        this.cooldown = 15;
        fireProjectile(this.x, this.y, target, this.damage, '#ff6644', 4);
      }
    }
  }

  draw() {
    const dw = this.w * TILE, dh = this.h * TILE;
    const drawX = this.x - dw / 2, drawY = this.y - dh / 2;

    if (drawX + dw < camX || drawX > camX + W || drawY + dh < camY || drawY > camY + H) return;

    const sx = drawX - camX, sy = drawY - camY;

    ctx.fillStyle = 'rgba(0,0,0,0.3)';
    ctx.fillRect(sx + 3, sy + 3, dw, dh);

    const alpha = Math.min(1, this.buildAnim * 2);
    ctx.globalAlpha = alpha;
    ctx.fillStyle = this.color;
    ctx.fillRect(sx, sy, dw, dh);
    ctx.strokeStyle = this.owner === 'player' ? '#4488ff' : '#ff4444';
    ctx.lineWidth = 2;
    ctx.strokeRect(sx, sy, dw, dh);

    ctx.fillStyle = 'rgba(0,0,0,0.12)';
    ctx.fillRect(sx + 4, sy + 4, dw - 8, dh - 8);
    ctx.fillStyle = 'rgba(255,255,255,0.06)';
    ctx.fillRect(sx + 4, sy + 4, dw - 8, 4);

    ctx.fillStyle = '#fff';
    ctx.font = '18px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(this.icon, this.x - camX, this.y - camY);

    const hpW = dw - 8;
    ctx.fillStyle = '#333';
    ctx.fillRect(sx + 4, sy - 8, hpW, 5);
    const hpRatio = this.hp / this.maxHp;
    ctx.fillStyle = hpRatio > 0.5 ? '#44cc44' : hpRatio > 0.25 ? '#cccc44' : '#cc4444';
    ctx.fillRect(sx + 4, sy - 8, hpW * hpRatio, 5);

    ctx.globalAlpha = 1;

    if (selectedBuilding === this) {
      ctx.strokeStyle = '#00ff00';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(sx - 3, sy - 3, dw + 6, dh + 6);
      ctx.setLineDash([]);
    }
  }
}

// ============================================================
// 单位类
// ============================================================
class Unit {
  constructor(type, x, y, owner = 'player', defs = UNIT_DEFS) {
    const d = defs[type];
    this.type = type;
    this.name = d.name;
    this.x = x;
    this.y = y;
    this.hp = d.hp;
    this.maxHp = d.hp;
    this.speed = d.speed;
    this.damage = d.damage;
    this.range = d.range;
    this.color = d.color;
    this.size = d.size;
    this.rof = d.rof;
    this.cooldown = 0;
    this.owner = owner;
    this.canSwim = d.canSwim || false;
    this.alive = true;

    this.path = [];
    this.pathIndex = 0;
    this.angle = Math.random() * Math.PI * 2;

    this.attackTarget = null;

    // 采矿
    this.isMining = false;
    this.carryingOre = 0;
    this.maxOre = 50;
    this.targetDeposit = null;
    this.homeRefinery = null;
    this.miningState = 'idle';
    this.miningTimer = 0;

    // 修理
    this.repairTarget = null;
    this.repairState = 'idle';
    this.repairTimer = 0;
    this.repairRate = d.repairRate || 0;
    this.repairRange = d.repairRange || 0;
  }

  setDestination(destX, destY) {
    this.path = findPath(this.x, this.y, destX, destY, this.canSwim);
    this.pathIndex = 0;
    this.attackTarget = null;
    this.isMining = false;
    this.targetDeposit = null;
    this.miningState = 'idle';
    this.repairTarget = null;
    this.repairState = 'idle';
  }

  setAttackTarget(target) {
    this.attackTarget = target;
    this.path = [];
    this.pathIndex = 0;
    this.isMining = false;
    this.miningState = 'idle';
    this.repairTarget = null;
    this.repairState = 'idle';
  }

  findNearestRefinery() {
    let best = null, bestDist = Infinity;
    for (const b of buildings) {
      if (!b.alive || b.owner !== 'player' || b.type !== 'ore_refinery') continue;
      const dx = b.x - this.x, dy = b.y - this.y;
      const dist = dx * dx + dy * dy;
      if (dist < bestDist) { bestDist = dist; best = b; }
    }
    return best;
  }

  update() {
    if (!this.alive) return;
    if (this.cooldown > 0) this.cooldown--;

    if (this.type === 'mining_truck' && this.owner === 'player' && !this.attackTarget) {
      this.updateMining();
      return;
    }

    if (this.type === 'repair_vehicle' && this.owner === 'player' && !this.attackTarget) {
      this.updateRepair();
      return;
    }

    // 检查当前攻击目标是否存活
    if (this.attackTarget) {
      if (this.attackTarget.alive) {
        const dx = this.attackTarget.x - this.x;
        const dy = this.attackTarget.y - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist <= this.range) {
          this.path = [];
          this.angle = Math.atan2(dy, dx);
          if (this.cooldown <= 0) {
            this.cooldown = this.rof;
            const pColor = this.owner === 'player' ? '#66ff66' : '#ff6666';
            fireProjectile(this.x, this.y, this.attackTarget, this.damage, pColor, this.type === 'tank' ? 5 : 3);
          }
        } else {
          if (this.path.length === 0 || this.pathIndex >= this.path.length) {
            const target = this.attackTarget;
            this.path = findPath(this.x, this.y, target.x, target.y, this.canSwim);
            this.pathIndex = 0;
          }
          this.followPath();
        }
      } else {
        // 目标已死亡，清除引用以便重新索敌
        this.attackTarget = null;
      }
    }

    // 沿路径移动时也扫描附近敌人
    if (this.path && this.pathIndex < this.path.length && !this.attackTarget) {
      this.followPath();
    }

    // 自动索敌：坦克拥有更大护卫范围
    if (!this.attackTarget && this.cooldown <= 0) {
      const searchRange = this.type === 'tank' ? this.range * 6 : this.range * 2;
      const enemy = findNearestEnemy(this.x, this.y, searchRange);
      if (enemy) this.attackTarget = enemy;
    }
  }

  updateMining() {
    switch (this.miningState) {
      case 'idle': {
        if (this.carryingOre > 0) {
          this.miningState = 'returning';
          const refinery = this.findNearestRefinery();
          if (refinery) {
            this.homeRefinery = refinery;
            this.path = findPath(this.x, this.y, refinery.x, refinery.y, this.canSwim);
            this.pathIndex = 0;
          }
          return;
        }
        const ore = this.findReachableOre();
        if (ore) {
          this.targetDeposit = ore;
          this.path = findPath(this.x, this.y, ore.x, ore.y, this.canSwim);
          this.pathIndex = 0;
          this.miningState = 'going_to_ore';
        }
        break;
      }
      case 'going_to_ore': {
        if (!this.targetDeposit || this.targetDeposit.amount <= 0) {
          this.miningState = 'idle';
          this.targetDeposit = null;
          return;
        }
        const dx = this.targetDeposit.x - this.x;
        const dy = this.targetDeposit.y - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 40) {
          this.miningState = 'mining';
          this.miningTimer = 0;
          this.path = [];
        } else {
          if (this.path.length === 0 || this.pathIndex >= this.path.length) {
            this.targetDeposit.amount = 0;
            this.miningState = 'idle';
            this.targetDeposit = null;
          } else {
            this.followPath();
          }
        }
        break;
      }
      case 'mining': {
        this.miningTimer++;
        if (this.miningTimer > 60) {
          const mined = Math.min(10, this.targetDeposit.amount, this.maxOre - this.carryingOre);
          this.targetDeposit.amount -= mined;
          this.carryingOre += mined;
          if (this.carryingOre >= this.maxOre || this.targetDeposit.amount <= 0) {
            this.miningState = 'returning';
            const refinery = this.findNearestRefinery();
            if (refinery) {
              this.homeRefinery = refinery;
              this.path = findPath(this.x, this.y, refinery.x, refinery.y, this.canSwim);
              this.pathIndex = 0;
            }
          }
          this.miningTimer = 0;
          for (let i = 0; i < 3; i++) {
            particles.push({
              x: this.x + (Math.random() - 0.5) * 16,
              y: this.y + (Math.random() - 0.5) * 16,
              vx: (Math.random() - 0.5) * 2,
              vy: -Math.random() * 2,
              life: 15 + Math.random() * 10,
              maxLife: 25,
              color: '#ffd700',
              size: 1.5 + Math.random() * 2,
            });
          }
        }
        break;
      }
      case 'returning': {
        if (!this.homeRefinery || !this.homeRefinery.alive) {
          this.homeRefinery = this.findNearestRefinery();
          if (!this.homeRefinery) return;
        }
        const dx = this.homeRefinery.x - this.x;
        const dy = this.homeRefinery.y - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 90) {
          const deposited = this.carryingOre;
          oreStored += deposited;
          this.carryingOre = 0;
          this.miningState = 'idle';
          this.targetDeposit = null;
          showStatus(`🪨 矿车入库 ${deposited} 矿石 (库存: ${oreStored})`);
        } else {
          if (this.path.length === 0 || this.pathIndex >= this.path.length) {
            this.path = findPath(this.x, this.y, this.homeRefinery.x, this.homeRefinery.y, this.canSwim);
            this.pathIndex = 0;
          }
          this.followPath();
        }
        break;
      }
    }
  }

  findReachableOre() {
    let best = null, bestDist = Infinity;
    for (const ore of oreDeposits) {
      if (ore.amount <= 0) continue;
      const dx = ore.x - this.x, dy = ore.y - this.y;
      const dist = dx * dx + dy * dy + Math.random() * 2500;
      if (dist < bestDist) { best = ore; bestDist = dist; }
    }
    return best;
  }

  // ---- 修理 ----
  findDamagedVehicle() {
    let best = null, bestDist = Infinity;
    for (const u of units) {
      if (!u.alive || u.owner !== 'player' || u === this) continue;
      if (u.hp >= u.maxHp) continue; // 满血跳过
      if (u.type === 'rifle') continue; // 不修步兵，只修车辆
      const dx = u.x - this.x, dy = u.y - this.y;
      const dist = dx * dx + dy * dy;
      if (dist < bestDist) { best = u; bestDist = dist; }
    }
    return best;
  }

  updateRepair() {
    switch (this.repairState) {
      case 'idle': {
        const target = this.findDamagedVehicle();
        if (target) {
          this.repairTarget = target;
          this.path = findPath(this.x, this.y, target.x, target.y, this.canSwim);
          this.pathIndex = 0;
          this.repairState = 'going_to_repair';
        }
        break;
      }
      case 'going_to_repair': {
        if (!this.repairTarget || !this.repairTarget.alive || this.repairTarget.hp >= this.repairTarget.maxHp) {
          this.repairTarget = null;
          this.repairState = 'idle';
          this.path = [];
          return;
        }
        const dx = this.repairTarget.x - this.x;
        const dy = this.repairTarget.y - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist <= this.repairRange) {
          this.path = [];
          this.repairState = 'repairing';
          this.repairTimer = 0;
        } else {
          if (this.path.length === 0 || this.pathIndex >= this.path.length) {
            this.path = findPath(this.x, this.y, this.repairTarget.x, this.repairTarget.y, this.canSwim);
            this.pathIndex = 0;
          }
          this.followPath();
        }
        break;
      }
      case 'repairing': {
        if (!this.repairTarget || !this.repairTarget.alive || this.repairTarget.hp >= this.repairTarget.maxHp) {
          // 修理完成，找下一个
          this.repairTarget = null;
          this.repairState = 'idle';
          return;
        }
        // 检查是否还在范围内
        const dx = this.repairTarget.x - this.x;
        const dy = this.repairTarget.y - this.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist > this.repairRange * 1.5) {
          this.repairState = 'going_to_repair';
          return;
        }

        this.repairTimer++;
        if (this.repairTimer >= 15) {
          this.repairTimer = 0;
          const healed = Math.min(this.repairRate, this.repairTarget.maxHp - this.repairTarget.hp);
          this.repairTarget.hp += healed;
          // 修理粒子效果
          for (let i = 0; i < 4; i++) {
            particles.push({
              x: this.repairTarget.x + (Math.random() - 0.5) * 20,
              y: this.repairTarget.y + (Math.random() - 0.5) * 20,
              vx: (Math.random() - 0.5) * 1.5,
              vy: -Math.random() * 1.5,
              life: 12 + Math.random() * 8,
              maxLife: 20,
              color: '#44ffcc',
              size: 1.5 + Math.random() * 2,
            });
          }
        }
        // 朝向目标，保持靠近
        this.angle = Math.atan2(dy, dx);
        if (dist > this.repairRange * 0.5 && this.pathIndex >= this.path.length) {
          this.path = findPath(this.x, this.y, this.repairTarget.x, this.repairTarget.y, this.canSwim);
          this.pathIndex = 0;
        }
        if (this.path && this.pathIndex < this.path.length) this.followPath();
        break;
      }
    }
  }

  followPath() {
    if (!this.path || this.pathIndex >= this.path.length) return;
    const target = this.path[this.pathIndex];
    const dx = target.x - this.x;
    const dy = target.y - this.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < 4) {
      this.pathIndex++;
    } else {
      const move = Math.min(this.speed, dist);
      this.x += (dx / dist) * move;
      this.y += (dy / dist) * move;
      this.angle = Math.atan2(dy, dx);
    }
  }

  draw() {
    if (!this.alive) return;
    const sx = this.x - camX, sy = this.y - camY;
    if (sx < -40 || sx > W + 40 || sy < -40 || sy > H + 40) return;

    const s = this.size;

    ctx.fillStyle = 'rgba(0,0,0,0.3)';
    ctx.beginPath();
    ctx.ellipse(sx + 2, sy + 3, s, s * 0.6, 0, 0, Math.PI * 2);
    ctx.fill();

    ctx.save();
    ctx.translate(sx, sy);
    ctx.rotate(this.angle);

    if (this.type === 'mining_truck') {
      ctx.fillStyle = this.color;
      ctx.fillRect(-s * 1.4, -s * 0.7, s * 2.8, s * 1.4);
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fillRect(-s * 1.4, -s * 0.7, s * 2.8, s * 0.35);
      ctx.fillStyle = '#886633';
      ctx.fillRect(-s * 0.8, -s * 0.5, s * 1.6, s * 1.0);
      if (this.carryingOre > 0) {
        ctx.fillStyle = '#ffd700';
        const oreH = (this.carryingOre / this.maxOre) * s * 0.8;
        ctx.fillRect(-s * 0.6, -s * 0.4 + s * 0.8 - oreH, s * 1.2, oreH);
      }
      ctx.fillStyle = '#444';
      ctx.fillRect(-s * 1.2, -s * 1.0, s * 0.5, s * 0.3);
      ctx.fillRect(-s * 1.2, s * 0.7, s * 0.5, s * 0.3);
      ctx.fillRect(s * 0.7, -s * 1.0, s * 0.5, s * 0.3);
      ctx.fillRect(s * 0.7, s * 0.7, s * 0.5, s * 0.3);
      ctx.restore();
      if (this.carryingOre > 0) {
        ctx.fillStyle = '#ffd700';
        ctx.font = '9px Arial';
        ctx.textAlign = 'center';
        ctx.fillText(`🪨${this.carryingOre}`, sx, sy - s - 10);
      }
      if (this.miningState === 'mining') {
        ctx.fillStyle = '#ffd700';
        ctx.beginPath();
        ctx.arc(sx, sy, s + 6 + Math.sin(gameTick * 0.1) * 2, 0, Math.PI * 2);
        ctx.stroke();
      }
      this.drawSelection(sx, sy, s);
      return;
    }

    // 修理车绘制
    if (this.type === 'repair_vehicle') {
      ctx.fillStyle = this.color;
      ctx.fillRect(-s * 1.4, -s * 0.7, s * 2.8, s * 1.4);
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fillRect(-s * 1.4, -s * 0.7, s * 2.8, s * 0.35);
      // 工具箱
      ctx.fillStyle = '#338877';
      ctx.fillRect(-s * 0.7, -s * 0.5, s * 1.4, s * 1.0);
      // 扳手图标
      ctx.fillStyle = '#66ffcc';
      ctx.fillRect(-s * 0.15, -s * 0.3, s * 0.3, s * 0.7);
      ctx.fillRect(-s * 0.15, s * 0.2, s * 0.7, s * 0.3);
      // 轮子
      ctx.fillStyle = '#444';
      ctx.fillRect(-s * 1.2, -s * 1.0, s * 0.5, s * 0.3);
      ctx.fillRect(-s * 1.2, s * 0.7, s * 0.5, s * 0.3);
      ctx.fillRect(s * 0.7, -s * 1.0, s * 0.5, s * 0.3);
      ctx.fillRect(s * 0.7, s * 0.7, s * 0.5, s * 0.3);
      ctx.restore();
      // 修理状态显示
      if (this.repairState === 'repairing' && this.repairTarget) {
        ctx.fillStyle = '#44ffcc';
        ctx.font = '9px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('🔧', sx, sy - s - 10);
        // 修理连线
        ctx.setLineDash([2, 3]);
        ctx.strokeStyle = 'rgba(68,255,204,0.3)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(this.repairTarget.x - camX, this.repairTarget.y - camY);
        ctx.stroke();
        ctx.setLineDash([]);
      } else if (this.repairTarget) {
        ctx.fillStyle = '#88ddcc';
        ctx.font = '9px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('➡️', sx, sy - s - 10);
      }
      this.drawSelection(sx, sy, s);
      return;
    }

    if (this.type === 'tank' || this.type === 'enemy_tank') {
      ctx.fillStyle = this.color;
      ctx.fillRect(-s * 1.2, -s * 0.8, s * 2.4, s * 1.6);
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fillRect(-s * 1.2, -s * 0.8, s * 2.4, s * 0.4);
      ctx.fillStyle = '#666';
      ctx.fillRect(s * 0.5, -s * 0.2, s * 1.5, s * 0.4);
      ctx.fillStyle = this.color;
      ctx.beginPath();
      ctx.arc(0, 0, s * 0.6, 0, Math.PI * 2);
      ctx.fill();
    } else if (this.type === 'jeep' || this.type === 'enemy_jeep') {
      ctx.fillStyle = this.color;
      ctx.fillRect(-s * 1.4, -s * 0.6, s * 2.8, s * 1.2);
      ctx.fillStyle = 'rgba(0,0,0,0.2)';
      ctx.fillRect(-s * 1.4, -s * 0.6, s * 2.8, s * 0.3);
      ctx.fillStyle = '#444';
      ctx.fillRect(-s * 1.1, -s * 0.9, s * 0.5, s * 0.3);
      ctx.fillRect(-s * 1.1, s * 0.6, s * 0.5, s * 0.3);
      ctx.fillRect(s * 0.6, -s * 0.9, s * 0.5, s * 0.3);
      ctx.fillRect(s * 0.6, s * 0.6, s * 0.5, s * 0.3);
    } else {
      ctx.fillStyle = this.color;
      ctx.beginPath();
      ctx.arc(0, 0, s, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#444';
      ctx.fillRect(s * 0.3, -s * 0.2, s * 1.0, s * 0.3);
      ctx.fillStyle = '#ffcc99';
      ctx.beginPath();
      ctx.arc(-s * 0.2, -s * 0.3, s * 0.4, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();
    this.drawHealthBar(sx, sy, s);
    this.drawSelection(sx, sy, s);
  }

  drawHealthBar(sx, sy, s) {
    const hpW = s * 3;
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(sx - hpW / 2, sy - s - 6, hpW, 4);
    const hpRatio = this.hp / this.maxHp;
    ctx.fillStyle = hpRatio > 0.5 ? '#44cc44' : hpRatio > 0.25 ? '#cccc44' : '#cc4444';
    ctx.fillRect(sx - hpW / 2 + 1, sy - s - 5, (hpW - 2) * hpRatio, 3);
  }

  drawSelection(sx, sy, s) {
    if (selectedUnits.includes(this)) {
      ctx.strokeStyle = '#00ff00';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(sx, sy, s + 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.strokeStyle = 'rgba(0,255,0,0.15)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(sx, sy, s + 8, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  takeDamage(dmg) {
    this.hp -= dmg;
    if (this.hp <= 0) {
      this.hp = 0;
      this.alive = false;
      for (let i = 0; i < 20; i++) {
        particles.push({
          x: this.x, y: this.y,
          vx: (Math.random() - 0.5) * 5,
          vy: (Math.random() - 0.5) * 5 - 1,
          life: 25 + Math.random() * 25,
          maxLife: 50,
          color: ['#ff6600', '#ff4400', '#ffaa00', '#ffcc00'][Math.floor(Math.random() * 4)],
          size: 2 + Math.random() * 3,
        });
      }
    }
  }
}

// ============================================================
// 弹丸
// ============================================================
function fireProjectile(fromX, fromY, target, damage, color, size = 3) {
  projectiles.push({
    x: fromX, y: fromY, target, speed: 5, damage, color, alive: true, size,
  });
}

// ============================================================
// 辅助函数
// ============================================================
function findNearestEnemy(x, y, maxRange) {
  let best = null, bestDist = maxRange;
  for (const u of units) {
    if (!u.alive || u.owner === 'player') continue;
    const dx = u.x - x, dy = u.y - y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < bestDist) { bestDist = dist; best = u; }
  }
  for (const b of buildings) {
    if (!b.alive || b.owner === 'player' || b.type === 'construction_yard') continue;
    const dx = b.x - x, dy = b.y - y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < bestDist) { bestDist = dist; best = b; }
  }
  return best;
}

function findNearestPlayerUnit(x, y, maxRange) {
  let best = null, bestDist = maxRange;
  for (const u of units) {
    if (!u.alive || u.owner !== 'player') continue;
    const dx = u.x - x, dy = u.y - y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < bestDist) { bestDist = dist; best = u; }
  }
  return best;
}

function canPlaceAt(tx, ty, w, h) {
  if (tx < 0 || ty < 0 || tx + w > MAP_COLS || ty + h > MAP_ROWS) return false;
  for (let dy = 0; dy < h; dy++) {
    for (let dx = 0; dx < w; dx++) {
      if (isWater(tx + dx, ty + dy)) return false;
      const cx = (tx + dx) * TILE + TILE / 2, cy = (ty + dy) * TILE + TILE / 2;
      for (const b of buildings) {
        if (!b.alive) continue;
        if (cx >= b.x - b.w * TILE / 2 && cx < b.x + b.w * TILE / 2 &&
            cy >= b.y - b.h * TILE / 2 && cy < b.y + b.h * TILE / 2) return false;
      }
    }
  }
  return true;
}

// ============================================================
// 建造 / 训练
// ============================================================
function placeBuilding(type) {
  const def = BUILDING_DEFS[type];
  if (credits < def.cost) { showStatus('💰 资金不足！'); return; }
  if (power <= 0 && def.power < 0) { showStatus('⚡ 电力不足！'); return; }
  isPlacing = { type, w: def.w, h: def.h, cost: def.cost, power: def.power };
  showStatus(`点击地图放置 ${def.name} ($${def.cost})`);
}

function confirmPlaceBuilding(tx, ty) {
  if (!isPlacing) return;
  const { type, w, h, cost, power: p } = isPlacing;
  if (!canPlaceAt(tx, ty, w, h)) { showStatus('❌ 该位置无法建造（注意避开水面）'); return; }
  credits -= cost;
  maxPower += p;
  power += p;
  const b = new Building(type, tx, ty, 'player');
  buildings.push(b);
  isPlacing = null;
  showStatus(`✅ ${BUILDING_DEFS[type].name} 建造完成`);
  updateUI();
}

function trainUnit(type) {
  const def = UNIT_DEFS[type];
  const hasFactory = buildings.some(b => b.alive && (b.type === 'barracks' || b.type === 'war_factory'));
  if (!hasFactory) { showStatus('❌ 需要先建造兵营或战车工厂'); return; }
  if (credits < def.cost) { showStatus('💰 资金不足！'); return; }

  const factory = buildings.find(b => b.alive && (b.type === 'barracks' || b.type === 'war_factory'));
  if (!factory) return;

  credits -= def.cost;
  const spawnX = factory.x + (factory.w * TILE / 2 + 30);
  const spawnY = factory.y + (Math.random() - 0.5) * 20;

  const u = new Unit(type, spawnX, spawnY, 'player');
  units.push(u);
  showStatus(`✅ ${def.name} 已部署`);
  updateUI();
}

// ============================================================
// 敌军 AI
// ============================================================
function spawnEnemyWave() {
  const wave = Math.floor(gameTick / 1800) + 1;
  const count = Math.min(2 + wave, 12);

  for (let i = 0; i < count; i++) {
    let x, y;
    const side = Math.floor(Math.random() * 4);
    switch (side) {
      case 0: x = Math.random() * MAP_COLS * TILE; y = -10; break;
      case 1: x = MAP_COLS * TILE + 10; y = Math.random() * MAP_ROWS * TILE; break;
      case 2: x = Math.random() * MAP_COLS * TILE; y = MAP_ROWS * TILE + 10; break;
      case 3: x = -10; y = Math.random() * MAP_ROWS * TILE; break;
    }

    const tx = Math.floor(x / TILE), ty = Math.floor(y / TILE);
    if (tx >= 0 && tx < MAP_COLS && ty >= 0 && ty < MAP_ROWS && isWater(tx, ty)) continue;

    let type;
    if (wave < 3) type = Math.random() < 0.7 ? 'infantry' : 'enemy_jeep';
    else if (wave < 6) type = Math.random() < 0.4 ? 'infantry' : Math.random() < 0.7 ? 'enemy_jeep' : 'enemy_tank';
    else type = Math.random() < 0.3 ? 'infantry' : Math.random() < 0.5 ? 'enemy_jeep' : 'enemy_tank';

    const u = new Unit(type, x, y, 'enemy', ENEMY_DEFS);
    const target = findNearestPlayerUnit(x, y, 9999) || buildings.find(b => b.alive && b.owner === 'player');
    if (target) {
      const path = findPath(x, y, target.x, target.y, false);
      if (path.length > 0) {
        u.path = path;
        u.pathIndex = 0;
        u.setAttackTarget(target);
        units.push(u);
      }
    }
  }
  showStatus(`🚨 敌军来袭！第 ${wave} 波 (${count} 单位)`);
}

// ============================================================
// 精炼厂自动转换矿石
// ============================================================
function processOre() {
  let refineryCount = buildings.filter(b => b.alive && b.owner === 'player' && b.type === 'ore_refinery').length;
  if (refineryCount > 0 && oreStored > 0) {
    const processed = Math.min(5, oreStored);
    oreStored -= processed;
    credits += processed * 20;
  }
}

// ============================================================
// 游戏更新
// ============================================================
function update() {
  if (gameOver) return;
  gameTick++;

  for (const b of buildings) if (b.alive) b.update();
  for (const u of units) if (u.alive) u.update();

  // 弹丸
  for (const p of projectiles) {
    if (!p.alive) continue;
    if (!p.target || !p.target.alive) { p.alive = false; continue; }
    const dx = p.target.x - p.x, dy = p.target.y - p.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 8) {
      p.target.takeDamage(p.damage);
      p.alive = false;
      for (let i = 0; i < 8; i++) {
        particles.push({
          x: p.target.x, y: p.target.y,
          vx: (Math.random() - 0.5) * 4,
          vy: (Math.random() - 0.5) * 4,
          life: 8 + Math.random() * 12,
          maxLife: 20, color: p.color, size: 1.5 + Math.random() * 2.5,
        });
      }
    } else {
      const move = Math.min(p.speed, dist);
      p.x += (dx / dist) * move;
      p.y += (dy / dist) * move;
    }
  }
  projectiles = projectiles.filter(p => p.alive);

  // 粒子
  for (const p of particles) { p.x += p.vx; p.y += p.vy; p.vy += 0.05; p.life--; }
  particles = particles.filter(p => p.life > 0);

  // 清理死亡单位
  units = units.filter(u => u.alive);
  buildings = buildings.filter(b => b.alive);

  // 清理选中单位中的死亡引用
  selectedUnits = selectedUnits.filter(u => u.alive);

  // 每 10 帧处理一次矿石
  processOre(); // 每帧处理矿石兑换

  // 资金收入
  if (gameTick % 60 === 0) {
    credits += 1 + Math.floor(buildings.filter(b => b.alive && b.owner === 'player' && b.type !== 'construction_yard').length * 0.3);
  }

  // 敌军生成
  enemySpawnTimer++;
  const spawnInterval = Math.max(300, 600 - gameTick / 60);
  if (enemySpawnTimer > spawnInterval) {
    enemySpawnTimer = 0;
    spawnEnemyWave();
  }

  // 镜头控制
  handleCamera();

  // 游戏结束检查
  const playerBlds = buildings.filter(b => b.alive && b.owner === 'player');
  const playerUnits = units.filter(u => u.alive && u.owner === 'player');
  const hasBase = playerBlds.some(b => b.type === 'construction_yard');
  if (!hasBase && playerUnits.length === 0 && playerBlds.length === 0) {
    gameOver = true;
    showStatus('💀 游戏结束！你被击败了... 刷新页面重试');
  }

  updateUI();
  drawMinimap();
}

function handleCamera() {
  const maxCamX = MAP_COLS * TILE - W;
  const maxCamY = MAP_ROWS * TILE - H;

  // WASD / 方向键
  if (keys['KeyW'] || keys['ArrowUp']) camY -= CAM_SPEED;
  if (keys['KeyS'] || keys['ArrowDown']) camY += CAM_SPEED;
  if (keys['KeyA'] || keys['ArrowLeft']) camX -= CAM_SPEED;
  if (keys['KeyD'] || keys['ArrowRight']) camX += CAM_SPEED;

  // 鼠标边缘滚动
  if (mouseOnCanvas) {
    const EDGE = 30;
    if (mouseScreenY < EDGE) camY -= CAM_SPEED;
    if (mouseScreenY > H - EDGE) camY += CAM_SPEED;
    if (mouseScreenX < EDGE) camX -= CAM_SPEED;
    if (mouseScreenX > W - EDGE) camX += CAM_SPEED;
  }

  camX = Math.max(0, Math.min(maxCamX, camX));
  camY = Math.max(0, Math.min(maxCamY, camY));
}

// ============================================================
// 绘图
// ============================================================
function draw() {
  ctx.clearRect(0, 0, W, H);

  // 使用离屏缓存绘制地形
  drawTerrainCached();
  drawOreDeposits();

  if (isPlacing) drawPlacementPreview();

  for (const b of buildings) b.draw();

  // 绘制路径
  for (const u of selectedUnits) {
    if (u.path && u.path.length > 1) {
      ctx.strokeStyle = 'rgba(0,255,0,0.3)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 5]);
      ctx.beginPath();
      for (let i = u.pathIndex; i < u.path.length; i++) {
        const sx = u.path[i].x - camX, sy = u.path[i].y - camY;
        if (i === u.pathIndex) ctx.moveTo(sx, sy);
        else ctx.lineTo(sx, sy);
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  for (const u of units) u.draw();

  // 框选矩形
  drawSelectionBox();

  for (const p of projectiles) {
    if (!p.alive) continue;
    const sx = p.x - camX, sy = p.y - camY;
    if (sx < -10 || sx > W + 10 || sy < -10 || sy > H + 10) continue;
    ctx.fillStyle = p.color;
    ctx.shadowColor = p.color;
    ctx.shadowBlur = 10;
    ctx.beginPath();
    ctx.arc(sx, sy, p.size, 0, Math.PI * 2);
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  for (const p of particles) {
    const sx = p.x - camX, sy = p.y - camY;
    if (sx < -10 || sx > W + 10 || sy < -10 || sy > H + 10) continue;
    const alpha = p.life / p.maxLife;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = p.color;
    ctx.fillRect(sx - p.size / 2, sy - p.size / 2, p.size, p.size);
  }
  ctx.globalAlpha = 1;

  // 水面波纹动画覆盖
  drawWaterWaves();

  if (gameOver) {
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = '#ff4444';
    ctx.font = 'bold 48px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('游戏结束', W / 2, H / 2 - 20);
    ctx.font = '20px Arial';
    ctx.fillStyle = '#aaa';
    ctx.fillText('刷新页面重新开始', W / 2, H / 2 + 40);
  }
}

function drawTerrainCached() {
  if (!terrainCache) return;
  // 直接绘制缓存的整个地形，利用 drawImage 的裁剪
  ctx.drawImage(terrainCache, camX, camY, W, H, 0, 0, W, H);
}

function drawWaterWaves() {
  const startTX = Math.max(0, Math.floor(camX / TILE));
  const startTY = Math.max(0, Math.floor(camY / TILE));
  const endTX = Math.min(MAP_COLS, Math.ceil((camX + W) / TILE));
  const endTY = Math.min(MAP_ROWS, Math.ceil((camY + H) / TILE));

  for (let y = startTY; y < endTY; y++) {
    for (let x = startTX; x < endTX; x++) {
      if (terrainMap[y][x] !== 1) continue;
      const sx = x * TILE - camX, sy = y * TILE - camY;
      const wave = Math.sin(gameTick * 0.02 + x * 0.5 + y * 0.7) * 0.15 + 0.15;
      ctx.fillStyle = `rgba(255,255,255,${wave * 0.05})`;
      ctx.beginPath();
      ctx.ellipse(sx + TILE / 2, sy + TILE * 0.6, TILE * 0.3, 2, 0, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawOreDeposits() {
  for (const ore of oreDeposits) {
    if (ore.amount <= 0) continue;
    const sx = ore.x - camX, sy = ore.y - camY;
    if (sx < -20 || sx > W + 20 || sy < -20 || sy > H + 20) continue;
    const size = ore.size * (ore.amount / ore.maxAmount);
    ctx.fillStyle = '#55aa33';
    ctx.beginPath();
    ctx.arc(sx, sy, size + 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#88cc44';
    ctx.beginPath();
    ctx.arc(sx, sy, size, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#aadd66';
    ctx.beginPath();
    ctx.arc(sx - 2, sy - 2, size * 0.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = `rgba(255,255,200,${0.2 + Math.sin(gameTick * 0.05 + ore.x) * 0.1})`;
    ctx.beginPath();
    ctx.arc(sx, sy, size + 5, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawPlacementPreview() {
  if (!isPlacing) return;
  const { w, h } = isPlacing;
  const tx = Math.floor(mouseWorldX / TILE), ty = Math.floor(mouseWorldY / TILE);
  const valid = canPlaceAt(tx, ty, w, h);
  const sx = tx * TILE - camX, sy = ty * TILE - camY;

  ctx.fillStyle = valid ? 'rgba(0,255,0,0.2)' : 'rgba(255,0,0,0.2)';
  ctx.fillRect(sx, sy, w * TILE, h * TILE);
  ctx.strokeStyle = valid ? '#00ff00' : '#ff0000';
  ctx.lineWidth = 2;
  ctx.strokeRect(sx, sy, w * TILE, h * TILE);
}

// ============================================================
// 小地图（缓存优化版）
// ============================================================
function drawMinimap() {
  const mw = minimapCanvas.width, mh = minimapCanvas.height;
  const scaleX = mw / (MAP_COLS * TILE);
  const scaleY = mh / (MAP_ROWS * TILE);

  // 绘制缓存的地形
  if (minimapTerrainCache) {
    minimapCtx.clearRect(0, 0, mw, mh);
    minimapCtx.drawImage(minimapTerrainCache, 0, 0);
  }

  // 矿石
  for (const ore of oreDeposits) {
    if (ore.amount <= 0) continue;
    minimapCtx.fillStyle = '#88cc44';
    minimapCtx.fillRect(ore.x * scaleX - 1, ore.y * scaleY - 1, 3, 3);
  }

  // 建筑
  for (const b of buildings) {
    if (!b.alive) continue;
    minimapCtx.fillStyle = b.owner === 'player' ? '#4488ff' : '#ff4444';
    minimapCtx.fillRect(b.x * scaleX - 2, b.y * scaleY - 2, 4, 4);
  }

  // 单位
  for (const u of units) {
    if (!u.alive) continue;
    minimapCtx.fillStyle = u.owner === 'player' ? '#66ff66' : '#ff6666';
    minimapCtx.fillRect(u.x * scaleX - 1, u.y * scaleY - 1, 2, 2);
  }

  // 镜头框
  minimapCtx.strokeStyle = '#fff';
  minimapCtx.lineWidth = 1;
  minimapCtx.strokeRect(camX * scaleX, camY * scaleY, W * scaleX, H * scaleY);
}

// 小地图点击跳转
minimapCanvas.addEventListener('click', (e) => {
  const rect = minimapCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const scaleX = MAP_COLS * TILE / minimapCanvas.width;
  const scaleY = MAP_ROWS * TILE / minimapCanvas.height;
  camX = Math.max(0, Math.min(MAP_COLS * TILE - W, mx * scaleX - W / 2));
  camY = Math.max(0, Math.min(MAP_ROWS * TILE - H, my * scaleY - H / 2));
});

// ============================================================
// 输入
// ============================================================
canvas.addEventListener('mousemove', (e) => {
  const rect = canvas.getBoundingClientRect();
  const sx = (e.clientX - rect.left) * (canvas.width / rect.width);
  const sy = (e.clientY - rect.top) * (canvas.height / rect.height);
  mouseScreenX = sx;
  mouseScreenY = sy;
  mouseWorldX = sx + camX;
  mouseWorldY = sy + camY;
  if (isDragging) {
    dragEndWorldX = mouseWorldX;
    dragEndWorldY = mouseWorldY;
  }
  document.getElementById('coordDisplay').textContent =
    `${Math.floor(mouseWorldX)},${Math.floor(mouseWorldY)}`;
});

canvas.addEventListener('mouseenter', () => { mouseOnCanvas = true; });
canvas.addEventListener('mouseleave', () => { mouseOnCanvas = false; });

canvas.addEventListener('contextmenu', (e) => e.preventDefault());

canvas.addEventListener('mousedown', (e) => {
  isMouseDown = true;
  if (gameOver) return;
  const mx = e.clientX - canvas.getBoundingClientRect().left;
  const my = e.clientY - canvas.getBoundingClientRect().top;
  const scaleX = canvas.width / canvas.getBoundingClientRect().width;
  const scaleY = canvas.height / canvas.getBoundingClientRect().height;
  const wx = mx * scaleX + camX;
  const wy = my * scaleY + camY;
  const tx = Math.floor(wx / TILE), ty = Math.floor(wy / TILE);

  if (e.button === 0) {
    if (isPlacing) { confirmPlaceBuilding(tx, ty); return; }

    // 开始框选
    isDragging = true;
    dragStartWorldX = wx;
    dragStartWorldY = wy;
    dragEndWorldX = wx;
    dragEndWorldY = wy;
  } else if (e.button === 2) {
    if (selectedUnits.length > 0) {
      let targetEnemy = null;
      for (const u of units) {
        if (!u.alive || u.owner === 'player') continue;
        const dx = wx - u.x, dy = wy - u.y;
        if (dx * dx + dy * dy < u.size * u.size * 6) { targetEnemy = u; break; }
      }
      for (const unit of selectedUnits) {
        if (targetEnemy) unit.setAttackTarget(targetEnemy);
        else unit.setDestination(wx, wy);
      }
    }
  }
});

canvas.addEventListener('mouseup', (e) => {
  if (e.button !== 0) return;
  if (!isDragging) return;
  isDragging = false;

  const mx = e.clientX - canvas.getBoundingClientRect().left;
  const my = e.clientY - canvas.getBoundingClientRect().top;
  const scaleX = canvas.width / canvas.getBoundingClientRect().width;
  const scaleY = canvas.height / canvas.getBoundingClientRect().height;
  const wx = mx * scaleX + camX;
  const wy = my * scaleY + camY;

  dragEndWorldX = wx;
  dragEndWorldY = wy;

  const dragDist = Math.sqrt((wx - dragStartWorldX) ** 2 + (wy - dragStartWorldY) ** 2);

  if (dragDist < 8) {
    // 短距离视为点击：沿用原有单点选择逻辑
    singleClickSelect(wx, wy, e.shiftKey);
  } else {
    // 框选
    boxSelect(e.shiftKey);
    updateUI();
  }
});

document.addEventListener('keydown', (e) => {
  keys[e.code] = true;
  if (e.code === 'Escape') { isPlacing = null; showStatus('已取消'); }
  // 防止方向键/WASD 滚动页面
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'KeyW', 'KeyA', 'KeyS', 'KeyD'].includes(e.code)) {
    e.preventDefault();
  }
});

document.addEventListener('keyup', (e) => { keys[e.code] = false; });
document.addEventListener('mouseup', () => { isMouseDown = false; });
document.addEventListener('blur', () => { isMouseDown = false; });

// ============================================================
// UI
// ============================================================
function singleClickSelect(wx, wy, shiftKey) {
  // 点击矿脉
  for (const ore of oreDeposits) {
    if (ore.amount <= 0) continue;
    const dx = wx - ore.x, dy = wy - ore.y;
    if (dx * dx + dy * dy < ore.size * ore.size * 3) {
      selectedUnits = [];
      selectedBuilding = null;
      showStatus(`🪨 矿脉储量: ${Math.floor(ore.amount)}/${ore.maxAmount}`);
      updateUI();
      return;
    }
  }

  // 点击单位
  let clickedUnit = null;
  for (const u of units) {
    if (!u.alive || u.owner !== 'player') continue;
    const dx = wx - u.x, dy = wy - u.y;
    if (dx * dx + dy * dy < u.size * u.size * 4) { clickedUnit = u; break; }
  }

  if (clickedUnit) {
    if (!shiftKey) selectedUnits = [];
    if (!selectedUnits.includes(clickedUnit)) selectedUnits.push(clickedUnit);
    selectedBuilding = null;
    updateUI();
  } else {
    // 点击建筑
    let clickedBld = null;
    for (const b of buildings) {
      if (!b.alive || b.owner !== 'player') continue;
      if (wx >= b.x - b.w * TILE / 2 && wx < b.x + b.w * TILE / 2 &&
          wy >= b.y - b.h * TILE / 2 && wy < b.y + b.h * TILE / 2) { clickedBld = b; break; }
    }
    if (clickedBld) {
      selectedBuilding = clickedBld;
      selectedUnits = [];
      updateUI();
    } else {
      if (!shiftKey) selectedUnits = [];
      selectedBuilding = null;
      updateUI();
    }
  }
}

function boxSelect(shiftKey) {
  // 框选矩形（世界坐标）
  const minX = Math.min(dragStartWorldX, dragEndWorldX);
  const maxX = Math.max(dragStartWorldX, dragEndWorldX);
  const minY = Math.min(dragStartWorldY, dragEndWorldY);
  const maxY = Math.max(dragStartWorldY, dragEndWorldY);

  if (!shiftKey) selectedUnits = [];
  selectedBuilding = null;

  let count = 0;
  for (const u of units) {
    if (!u.alive || u.owner !== 'player') continue;
    if (u.x >= minX && u.x <= maxX && u.y >= minY && u.y <= maxY) {
      if (!selectedUnits.includes(u)) {
        selectedUnits.push(u);
        count++;
      }
    }
  }
  showStatus(`📦 框选 ${count} 个单位`);
  updateUI();
}

function drawSelectionBox() {
  if (!isDragging) return;
  const minX = Math.min(dragStartWorldX, dragEndWorldX);
  const maxX = Math.max(dragStartWorldX, dragEndWorldX);
  const minY = Math.min(dragStartWorldY, dragEndWorldY);
  const maxY = Math.max(dragStartWorldY, dragEndWorldY);
  const sx = minX - camX, sy = minY - camY;
  const w = maxX - minX, h = maxY - minY;

  if (w < 2 && h < 2) return; // 太小不画

  ctx.fillStyle = 'rgba(0,255,0,0.08)';
  ctx.fillRect(sx, sy, w, h);
  ctx.strokeStyle = 'rgba(0,255,0,0.6)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.strokeRect(sx, sy, w, h);
  ctx.setLineDash([]);
}

function showStatus(msg) {
  document.getElementById('selInfo').textContent = msg;
}

function updateUI() {
  document.getElementById('creditsDisplay').textContent = `💰 ${Math.floor(credits)}`;
  document.getElementById('oreDisplay').textContent = `🪨 ${oreStored}`;
  document.getElementById('powerDisplay').textContent = `⚡ ${power}/${maxPower}`;
  document.getElementById('enemyCount').textContent = units.filter(u => u.alive && u.owner === 'enemy').length;

  const selInfo = document.getElementById('selInfo');
  const unitDetail = document.getElementById('unitDetail');

  if (selectedUnits.length > 0) {
    selInfo.textContent = `${selectedUnits.length} 个单位`;
    if (selectedUnits.length === 1) {
      const u = selectedUnits[0];
      let extra = '';
      if (u.type === 'mining_truck') extra = ` 🪨${u.carryingOre}/${u.maxOre}`;
      if (u.type === 'repair_vehicle') extra = ` 🔧${u.repairState}`;
      if (u.type === 'repair_vehicle' && u.repairTarget) extra += ` →${u.repairTarget.name}`;
      unitDetail.textContent = `${u.name} HP:${Math.ceil(u.hp)}/${u.maxHp}${extra}`;
    } else {
      const alive = selectedUnits.filter(u => u.alive);
      unitDetail.textContent = `HP: ${alive.reduce((s, u) => s + Math.ceil(u.hp), 0)}`;
    }
  } else if (selectedBuilding) {
    selInfo.textContent = selectedBuilding.name;
    unitDetail.textContent = `HP: ${Math.ceil(selectedBuilding.hp)}/${selectedBuilding.maxHp}`;
  } else {
    selInfo.textContent = '无';
    unitDetail.textContent = '';
  }
}

// ============================================================
// 初始化
// ============================================================
function initGame() {
  generateTerrain();
  generateOre();

  const base = new Building('construction_yard', 4, 5, 'player');
  buildings.push(base);

  const pp = new Building('power_plant', 8, 5, 'player');
  buildings.push(pp);
  power = 70; maxPower = 70;

  const bar = new Building('barracks', 4, 9, 'player');
  buildings.push(bar);
  power -= 5;

  const refinery = new Building('ore_refinery', 8, 8, 'player');
  buildings.push(refinery);

  for (let i = 0; i < 3; i++) units.push(new Unit('rifle', 250 + i * 30, 380, 'player'));
  for (let i = 0; i < 2; i++) units.push(new Unit('mining_truck', 300 + i * 40, 420, 'player'));

  showStatus('🏛️ 建造基地，发展经济，抵御敌军！WASD/方向键/鼠标边缘移屏');
  canvas.focus();
  gameLoop();
}

function gameLoop() {
  update();
  draw();
  requestAnimationFrame(gameLoop);
}

initGame();
