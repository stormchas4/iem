"""Scrape out the Soil Bulk Density and Texture data from Google Drive"""
import util
import sys
import gdata.docs.client
import ConfigParser
import psycopg2

YEAR = sys.argv[1]

config = ConfigParser.ConfigParser()
config.read('mytokens.cfg')

pgconn = psycopg2.connect(database='sustainablecorn',
                          host=config.get('database', 'host'))
pcursor = pgconn.cursor()

# Get me a client, stat
spr_client = util.get_spreadsheet_client(config)
docs_client = util.get_docs_client(config)

query = gdata.docs.client.DocsQuery(show_collections='false', 
                                    title='Soil Bulk Density and Water Retention Data')
feed = docs_client.GetAllResources(query=query)

for entry in feed:
    if entry.get_resource_type() != 'spreadsheet':
        continue
    spreadsheet = util.Spreadsheet(docs_client, spr_client, entry)
    spreadsheet.get_worksheets()
    siteid = spreadsheet.title.split()[0]
    worksheet = spreadsheet.worksheets.get(YEAR)
    if worksheet is None:
        print 'Missing %s sheet for %s' % (YEAR, siteid)
        continue
    worksheet.get_cell_feed()
    #if siteid == 'DPAC':
    #    print 'ERROR: Skipping DPAC Soil Texture sheet as it has subsamples'
    #    continue
    #print 'Processing %s Soil BD & Water Retention Year %s' % (siteid, YEAR),
    if (worksheet.get_cell_value(1, 1) != 'plotid' or
        worksheet.get_cell_value(1, 2) != 'depth' or
        worksheet.get_cell_value(1, 3) != 'subsample'):
        print 'FATAL site: %s(%s) bd & wr has bad header 1:%s 2:%s 3:%s' % (
            siteid, YEAR, worksheet.get_cell_value(1, 1), 
            worksheet.get_cell_value(1, 2), 
            worksheet.get_cell_value(1, 3))
        continue
    
    #Load up current data, incase we need to do some deleting
    current = {}
    pcursor.execute("""SELECT plotid, varname, depth, subsample
    from soil_data WHERE site = %s and year = %s""", (siteid, YEAR))
    for row in pcursor:
        key = "%s|%s|%s|%s" % row
        current[key] = True
    found_vars = []
    for row in range(4,worksheet.rows+1):
        plotid = worksheet.get_cell_value(row, 1)
        depth = worksheet.get_cell_value(row, 2)
        subsample = worksheet.get_cell_value(row, 3)
        if plotid is None or depth is None:
            continue
        for col in range(4, worksheet.cols+1):
            varname = worksheet.get_cell_value(1,col).strip().split()[0]
            if varname[:4] != 'SOIL':
                #print 'Invalid varname: %s site: %s year: %s' % (
                #                    worksheet.get_cell_value(1,col).strip(),
                #                    siteid, YEAR)
                continue
            if not varname in found_vars:
                found_vars.append(varname)
            val = worksheet.get_cell_value(row, col)
            try:
                pcursor.execute("""
                    INSERT into soil_data(site, plotid, varname, year, 
                    depth, value, subsample)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    """, (siteid, plotid, varname, YEAR, depth, val, subsample))
            except Exception, exp:
                print 'HARVEST_SOIL_BD TRACEBACK'
                print exp
                print '%s %s %s %s %s %s' % (siteid, plotid, varname, depth, 
                                             val, subsample)
                sys.exit()
            key = "%s|%s|%s|%s" % (plotid, varname, depth, subsample)
            if current.has_key(key):
                del(current[key])
    for key in current:
        (plotid, varname, depth, subsample) = key.split("|")
        if varname in found_vars:
            print 'harvest_soil_bd REMOVE %s %s %s %s %s' % (siteid, plotid, 
                                                    varname, depth, subsample)
            pcursor.execute("""DELETE from soil_data where site = %s and 
            plotid = %s and varname = %s and year = %s and depth = %s and
            subsample = %s""", (siteid, plotid, varname, YEAR, depth,
                                subsample))

    #print "...done"
pcursor.close()
pgconn.commit()
pgconn.close()