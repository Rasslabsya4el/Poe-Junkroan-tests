-- Repo-owned Path of Building headless wrapper.
-- Based on upstream HeadlessWrapper.lua for the pinned PoB lane, with two
-- local adjustments:
-- 1. runtime and user roots come from environment variables so the host can
--    keep writable state out of the pinned cache;
-- 2. startup failures raise immediately instead of blocking on io.read().

local runtimeRoot = (os.getenv("POB_RUNTIME_ROOT") or ""):gsub("\\", "/")
local userRoot = (os.getenv("POB_HEADLESS_USER_PATH") or runtimeRoot):gsub("\\", "/")
local workDir = (os.getenv("POB_HEADLESS_WORKDIR") or userRoot):gsub("\\", "/")

local function joinRuntimePath(fileName)
	if runtimeRoot == "" then
		return fileName
	end
	if fileName:match("^%a:[/\\]") or fileName:sub(1, 1) == "/" then
		return fileName
	end
	return runtimeRoot .. "/" .. fileName
end

local hostZlib
local hostZlibLoadAttempted = false

local function getHostZlib()
	if not hostZlibLoadAttempted then
		hostZlibLoadAttempted = true
		local ok, ffi = pcall(require, "ffi")
		if ok then
			ffi.cdef[[
				typedef unsigned char Bytef;
				typedef unsigned long uLong;
				typedef unsigned long uLongf;
				int uncompress(Bytef *dest, uLongf *destLen, const Bytef *source, uLong sourceLen);
			]]
			local loaded, lib = pcall(ffi.load, joinRuntimePath("zlib1.dll"))
			if loaded then
				hostZlib = { ffi = ffi, lib = lib }
			end
		end
	end
	return hostZlib
end

if runtimeRoot ~= "" then
	package.path = package.path
		.. ";" .. runtimeRoot .. "/?.lua"
		.. ";" .. runtimeRoot .. "/?/init.lua"
		.. ";" .. runtimeRoot .. "/lua/?.lua"
		.. ";" .. runtimeRoot .. "/lua/?/init.lua"
		.. ";" .. runtimeRoot .. "/lua/?/?.lua"
	package.cpath = package.cpath .. ";" .. runtimeRoot .. "/?.dll"
end

arg = arg or {}

-- Callbacks
local callbackTable = { }
local mainObject
function runCallback(name, ...)
	if callbackTable[name] then
		return callbackTable[name](...)
	elseif mainObject and mainObject[name] then
		return mainObject[name](mainObject, ...)
	end
end
function SetCallback(name, func)
	callbackTable[name] = func
end
function GetCallback(name)
	return callbackTable[name]
end
function SetMainObject(obj)
	mainObject = obj
end

-- Image Handles
local imageHandleClass = { }
imageHandleClass.__index = imageHandleClass
function NewImageHandle()
	return setmetatable({ }, imageHandleClass)
end
function imageHandleClass:Load(fileName, ...)
	self.valid = true
end
function imageHandleClass:Unload()
	self.valid = false
end
function imageHandleClass:IsValid()
	return self.valid
end
function imageHandleClass:SetLoadingPriority(pri) end
function imageHandleClass:ImageSize()
	return 1, 1
end

-- Rendering
function RenderInit(flag, ...) end
function GetScreenSize()
	return 1920, 1080
end
function GetVirtualScreenSize()
	return GetScreenSize()
end
function GetScreenScale()
	return 1
end
function GetDPIScaleOverridePercent()
	return 1
end
function SetDPIScaleOverridePercent(scale) end
function SetClearColor(r, g, b, a) end
function SetDrawLayer(layer, subLayer) end
function SetViewport(x, y, width, height) end
function SetDrawColor(r, g, b, a) end
function DrawImage(imgHandle, left, top, width, height, tcLeft, tcTop, tcRight, tcBottom) end
function DrawImageQuad(imageHandle, x1, y1, x2, y2, x3, y3, x4, y4, s1, t1, s2, t2, s3, t3, s4, t4) end
function DrawString(left, top, align, height, font, text) end
function DrawStringWidth(height, font, text)
	return 1
end
function DrawStringCursorIndex(height, font, text, cursorX, cursorY)
	return 0
end
function StripEscapes(text)
	return text:gsub("%^%d",""):gsub("%^x%x%x%x%x%x%x","")
end
function GetAsyncCount()
	return 0
end

-- Search Handles
function NewFileSearch() end

-- General Functions
function SetWindowTitle(title) end
function GetCursorPos()
	return 0, 0
end
function SetCursorPos(x, y) end
function ShowCursor(doShow) end
function IsKeyDown(keyName)
	return false
end
function Copy(text) end
function Paste()
	return ""
end
function Deflate(data)
	return ""
end
function Inflate(data)
	if type(data) ~= "string" or data == "" then
		return nil
	end
	local zlib = getHostZlib()
	if not zlib then
		return nil
	end
	local sourceLen = #data
	local outSize = math.max(sourceLen * 8, 262144)
	local maxOutSize = 64 * 1024 * 1024
	while outSize <= maxOutSize do
		local out = zlib.ffi.new("unsigned char[?]", outSize)
		local outLen = zlib.ffi.new("unsigned long[1]", outSize)
		local source = zlib.ffi.cast("const unsigned char *", data)
		outLen[0] = outSize
		local rc = zlib.lib.uncompress(out, outLen, source, sourceLen)
		if rc == 0 then
			return zlib.ffi.string(out, tonumber(outLen[0]))
		end
		if rc ~= -5 then
			return nil
		end
		outSize = outSize * 2
	end
	return nil
end
function GetTime()
	return 0
end
function GetScriptPath()
	return runtimeRoot
end
function GetRuntimePath()
	return runtimeRoot
end
function GetUserPath()
	return userRoot
end
function MakeDir(path) end
function RemoveDir(path) end
function SetWorkDir(path)
	if type(path) == "string" and path ~= "" then
		workDir = path
	end
end
function GetWorkDir()
	return workDir
end
function LaunchSubScript(scriptText, funcList, subList, ...) end
function AbortSubScript(ssID) end
function IsSubScriptRunning(ssID)
	return false
end
function LoadModule(fileName, ...)
	if not fileName:match("%.lua") then
		fileName = fileName .. ".lua"
	end
	local resolvedName = joinRuntimePath(fileName)
	local func, err = loadfile(resolvedName)
	if func then
		return func(...)
	else
		error("LoadModule() error loading '"..resolvedName.."': "..err)
	end
end
function PLoadModule(fileName, ...)
	if not fileName:match("%.lua") then
		fileName = fileName .. ".lua"
	end
	local resolvedName = joinRuntimePath(fileName)
	local func, err = loadfile(resolvedName)
	if func then
		return PCall(func, ...)
	else
		error("PLoadModule() error loading '"..resolvedName.."': "..err)
	end
end
function PCall(func, ...)
	local ret = { pcall(func, ...) }
	if ret[1] then
		table.remove(ret, 1)
		return nil, unpack(ret)
	else
		return ret[2]
	end
end
function ConPrintf(fmt, ...) end
function ConPrintTable(tbl, noRecurse) end
function ConExecute(cmd) end
function ConClear() end
function SpawnProcess(cmdName, args) end
function OpenURL(url) end
function SetProfiling(isEnabled) end
function Restart() end
function Exit() end
function TakeScreenshot() end
function GetDeviceInfo()
	return {}
end

---@return string? provider
---@return string? version
---@return number? status
function GetCloudProvider(fullPath)
	return nil, nil, nil
end

local l_require = require
function require(name)
	if name == "lcurl.safe" then
		return
	end
	return l_require(name)
end

-- Launch.lua tunes LuaJIT (jit.opt.start('maxtrace=...','maxmcode=...')) before anything
-- else runs. Those two numbers are worth 2.4x on the optimizer's trial loop (measured
-- 2026-09-18 on stormbrand: 5.2-5.4 ms per fast trial with maxtrace=4000/maxmcode=8192,
-- 12.4-13.8 ms with LuaJIT's defaults and the trace cache visibly flushing), so the host
-- checks them at boot. LuaJIT has no getter for them: record what is actually applied.
headlessJitOptApplied = { }
if jit and jit.opt and jit.opt.start then
	local realJitOptStart = jit.opt.start
	jit.opt.start = function(...)
		local count = select("#", ...)
		for i = 1, count do
			local param = select(i, ...)
			if type(param) == "string" then
				local name, value = param:match("^(%a+)=(%d+)$")
				if name then
					headlessJitOptApplied[name] = tonumber(value)
				end
			end
		end
		return realJitOptStart(...)
	end
end

dofile(joinRuntimePath("Launch.lua"))

-- "status|version|maxtrace|maxmcode" for the host's boot-time JIT guard.
function headlessJitState()
	local status = jit and jit.status() or false
	return table.concat({
		tostring(status and true or false),
		tostring(jit and jit.version or ""),
		tostring(headlessJitOptApplied.maxtrace or ""),
		tostring(headlessJitOptApplied.maxmcode or ""),
	}, "|")
end

mainObject.continuousIntegrationMode = os.getenv("CI")

runCallback("OnInit")
runCallback("OnFrame")

if mainObject.promptMsg then
	error(mainObject.promptMsg)
end

build = mainObject.main.modes["BUILD"]

-- One dirty recalc (runCallback('OnFrame') with build.buildFlag set) runs PoB's
-- CalcsTab:BuildOutput, which is four full calculation passes. Measured 2026-09-18 on
-- stormbrand: 92 ms = MAIN lane 60 + CALCS lane 13 + node calculator 12 + misc calculator
-- 11 + 1 for the rest. This lane never draws the calculations tab (the CALCS lane is read
-- only by the calc snapshot, for reports), and PoB itself never calls
-- CalcsTab:GetNodeCalculator -- it has no caller anywhere in src/ -- so both are built on
-- demand instead of on every recalc. Every recalc clears `calcsEnv` / `calcsOutput` and
-- the first read after it rebuilds them, so no reader can see a stale CALCS lane.
local calcsTabClass = common and common.classes and common.classes["CalcsTab"]
if calcsTabClass then
	local function buildCalcsLane(self)
		if rawget(self, "headlessCalcsLaneBuilding") then
			return nil
		end
		rawset(self, "headlessCalcsLaneBuilding", true)
		local ok, env = pcall(self.calcs.buildOutput, self.build, "CALCS")
		rawset(self, "headlessCalcsLaneBuilding", nil)
		if not ok then
			error(env, 0)
		end
		rawset(self, "calcsEnv", env)
		rawset(self, "calcsOutput", env.player.output)
		return env
	end

	-- Witness stats the optimizer's keystone floors need in every readback, real or what-if
	-- (optimizer/keystone_floors.py): a tree keystone reaches the mod DB only as a "Keystone"
	-- LIST mod (ModTools.mergeKeystones records the names in env.keystonesAdded, reset by
	-- every calcs.perform), and PoB publishes an output for Precise Technique only
	-- (CalcOffence: output.PreciseTechnique). calcs.perform is the one call every lane and
	-- calculator goes through (Calcs.lua: buildOutput, getMiscCalculator, getNodeCalculator,
	-- calcFullDPS), so the witness is added there, after the pass.
	local function hookPerform(calcs)
		if rawget(calcs, "headlessPerformHooked") then
			return
		end
		local perform = calcs.perform
		calcs.perform = function(env, ...)
			perform(env, ...)
			local player = env and env.player
			if player and player.output then
				local added = env.keystonesAdded or {}
				player.output.HaveElementalOverload = added["Elemental Overload"] and 1 or 0
			end
		end
		rawset(calcs, "headlessPerformHooked", true)
	end

	function calcsTabClass:BuildOutput()
		hookPerform(self.calcs)
		self.powerBuildFlag = true
		for _, node in pairs(self.build.spec.nodes) do
			-- Set default final mod list for all nodes; some may not be set during the main pass
			node.finalModList = node.modList
		end
		self.mainEnv = self.calcs.buildOutput(self.build, "MAIN")
		self.mainOutput = self.mainEnv.player.output
		rawset(self, "calcsEnv", nil)
		rawset(self, "calcsOutput", nil)
		rawset(self, "nodeCalculator", nil)
		if self.displayData then
			self.controls.breakdown:SetBreakdownData()
			self.controls.breakdown:SetBreakdownData(self.displayData, self.displayPinned)
		end
		self.miscCalculator = { self.calcs.getMiscCalculator(self.build) }
	end

	function calcsTabClass:GetNodeCalculator()
		if not rawget(self, "nodeCalculator") then
			self.nodeCalculator = { self.calcs.getNodeCalculator(self.build) }
		end
		return unpack(self.nodeCalculator)
	end

	calcsTabClass.__index = function(tab, key)
		if key == "calcsOutput" or key == "calcsEnv" then
			local env = buildCalcsLane(tab)
			if key == "calcsEnv" then
				return env
			end
			return rawget(tab, "calcsOutput")
		end
		return calcsTabClass[key]
	end
end

function newBuild()
	mainObject.main:SetMode("BUILD", false, "Headless Proof Build")
	runCallback("OnFrame")
end
function loadBuildFromXML(xmlText, name)
	mainObject.main:SetMode("BUILD", false, name or "", xmlText)
	runCallback("OnFrame")
end
function loadBuildFromJSON(getItemsJSON, getPassiveSkillsJSON)
	mainObject.main:SetMode("BUILD", false, "")
	runCallback("OnFrame")
	local charData = build.importTab:ImportItemsAndSkills(getItemsJSON)
	build.importTab:ImportPassiveTreeAndJewels(getPassiveSkillsJSON, charData)
end
function verifyImportCodeString(importCode)
	mainObject.main:SetMode("BUILD", false, "Headless Import String Verification")
	runCallback("OnFrame")
	build = mainObject.main.modes["BUILD"]
	local importTab = build and build.importTab
	if not importTab or not importTab.controls or not importTab.controls.importCodeIn then
		error("ImportTab import-code input control is unavailable.")
	end
	importTab.controls.importCodeIn:SetText(importCode or "", true)
	runCallback("OnFrame")
	local valid = importTab.importCodeValid == true and type(importTab.importCodeXML) == "string" and #importTab.importCodeXML > 0
	local missingInput = ""
	local invalidReason = ""
	if not valid then
		invalidReason = "native_import_code_invalid"
	end
	if valid and importTab.controls.importCodeMode then
		importTab.controls.importCodeMode.selIndex = 2
	end
	if valid and importTab.controls.importCodeGo and importTab.controls.importCodeGo.onClick then
		importTab.controls.importCodeGo.onClick()
		runCallback("OnFrame")
		build = mainObject.main.modes["BUILD"]
	end
	return {
		status = valid and "accepted" or "invalid",
		import_code_valid = valid,
		native_pob_import_string_semantics_valid = valid,
		import_code_detail = importTab.importCodeDetail or "",
		decoded_xml_char_count = type(importTab.importCodeXML) == "string" and #importTab.importCodeXML or 0,
		imported_build_active = valid,
		missing_input = missingInput,
		invalid_reason = invalidReason,
	}
end
